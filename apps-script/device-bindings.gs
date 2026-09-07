/*
 * JACC Approach B — Separate device bindings and auth sessions.
 *
 * This file is intended to be added to the same Google Apps Script project as
 * Code.gs. It deliberately does not add or change any Members columns.
 *
 * Script Properties:
 *   JACC_DEVICE_HASH_SECRET — strong random secret used to hash identifiers.
 *   JACC_DEVICE_BINDING_MODE — enforce (default), log, or off.
 *
 * DeviceBindings columns:
 *   UserID, DeviceHash, ClientApp, BoundAt, LastSeenAt, Status,
 *   ResetCount, ResetAt
 *
 * AuthSessions columns:
 *   SessionHash, UserID, DeviceHash, ClientApp, IssuedAt, ExpiresAt,
 *   Status, RevokedAt, LastSeenAt
 */

var DEVICE_BINDINGS_SHEET = 'DeviceBindings';
var AUTH_SESSIONS_SHEET = 'AuthSessions';
var DEVICE_BINDING_MODE_PROPERTY = 'JACC_DEVICE_BINDING_MODE';
var DEVICE_HASH_SECRET_PROPERTY = 'JACC_DEVICE_HASH_SECRET';

var DEVICE_BINDING_HEADERS = [
  'UserID', 'DeviceHash', 'ClientApp', 'BoundAt', 'LastSeenAt',
  'Status', 'ResetCount', 'ResetAt'
];

var AUTH_SESSION_HEADERS = [
  'SessionHash', 'UserID', 'DeviceHash', 'ClientApp', 'IssuedAt',
  'ExpiresAt', 'Status', 'RevokedAt', 'LastSeenAt'
];

function _normalizeBindingText_(value, maxLength) {
  var text = String(value || '')
    .replace(/[\u0000-\u001F\u007F\u200B-\u200D\u2060\uFEFF]/g, '')
    .trim();
  if (maxLength && text.length > maxLength) text = text.slice(0, maxLength);
  return text;
}

function _normalizeBindingUserId_(value) {
  return _normalizeBindingText_(value, 40).replace(/\.0$/, '');
}

function _normalizeDeviceId_(value) {
  var text = _normalizeBindingText_(value, 160);
  if (!text || !/^[A-Za-z0-9._:-]{8,160}$/.test(text)) return '';
  return text;
}

function _normalizeClientApp_(value) {
  var app = _normalizeBindingText_(value, 20).toLowerCase();
  return app === 'flutter' || app === 'pwa' || app === 'web' ? app : 'web';
}

function _deviceBindingMode_() {
  var configured = String(PropertiesService.getScriptProperties()
    .getProperty(DEVICE_BINDING_MODE_PROPERTY) || '').trim().toLowerCase();
  if (configured === 'off' || configured === 'log' || configured === 'enforce') {
    return configured;
  }
  return 'enforce';
}

function _deviceHashSecret_() {
  var props = PropertiesService.getScriptProperties();
  return String(
    props.getProperty(DEVICE_HASH_SECRET_PROPERTY) ||
    props.getProperty('JACC_SERVER_KEY') ||
    ''
  ).trim();
}

function _sha256Hex_(value) {
  var bytes = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    String(value || ''),
    Utilities.Charset.UTF_8
  );
  return bytes.map(function(byte) {
    var unsigned = byte < 0 ? byte + 256 : byte;
    var hex = unsigned.toString(16);
    return hex.length === 1 ? '0' + hex : hex;
  }).join('');
}

function _hashDeviceId_(deviceId) {
  var normalized = _normalizeDeviceId_(deviceId);
  var secret = _deviceHashSecret_();
  if (!normalized || !secret) return '';
  return _sha256Hex_('jacc-device-v1:' + secret + ':' + normalized);
}

function _hashSessionToken_(token) {
  var secret = _deviceHashSecret_();
  var normalized = _normalizeBindingText_(token, 300);
  if (!normalized || !secret) return '';
  return _sha256Hex_('jacc-session-v1:' + secret + ':' + normalized);
}

function _ensureBindingSheet_(sheetName, headers) {
  var ss = SpreadsheetApp.openById(SS_ID);
  var sheet = ss.getSheetByName(sheetName);
  if (!sheet) {
    sheet = ss.insertSheet(sheetName);
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    sheet.setFrozenRows(1);
    return sheet;
  }

  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    sheet.setFrozenRows(1);
    return sheet;
  }

  var current = sheet.getRange(1, 1, 1, headers.length).getValues()[0];
  var hasAnyHeader = current.some(function(value) {
    return String(value || '').trim() !== '';
  });
  if (!hasAnyHeader) {
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    sheet.setFrozenRows(1);
    return sheet;
  }

  for (var i = 0; i < headers.length; i++) {
    if (String(current[i] || '').trim() !== headers[i]) {
      throw new Error('device_sheet_schema_mismatch:' + sheetName);
    }
  }
  return sheet;
}

function _deviceBindingsSheet_() {
  return _ensureBindingSheet_(DEVICE_BINDINGS_SHEET, DEVICE_BINDING_HEADERS);
}

function _authSessionsSheet_() {
  return _ensureBindingSheet_(AUTH_SESSIONS_SHEET, AUTH_SESSION_HEADERS);
}

function _findBindingRow_(sheet, userId) {
  var target = _normalizeBindingUserId_(userId);
  if (!target || sheet.getLastRow() < 2) return 0;
  var values = sheet.getRange(2, 1, sheet.getLastRow() - 1, 1).getValues();
  for (var i = 0; i < values.length; i++) {
    if (_normalizeBindingUserId_(values[i][0]) === target) return i + 2;
  }
  return 0;
}

function _findMemberRowByUserId_(sheet, userId) {
  var target = _normalizeBindingUserId_(userId);
  if (!target || sheet.getLastRow() < 2) return 0;
  var values = sheet.getRange(2, C_USERID + 1, sheet.getLastRow() - 1, 1).getValues();
  for (var i = 0; i < values.length; i++) {
    if (_normalizeBindingUserId_(values[i][0]) === target) return i + 2;
  }
  return 0;
}

function _verifyAndBindDevice_(userId, deviceId, app, options) {
  var mode = _deviceBindingMode_();
  var readOnly = !!(options && options.readOnly);
  var normalizedUserId = _normalizeBindingUserId_(userId);
  var normalizedDeviceId = _normalizeDeviceId_(deviceId);
  var clientApp = _normalizeClientApp_(app);

  if (mode === 'off') {
    return {ok: true, deviceBound: false, deviceHash: '', clientApp: clientApp};
  }

  if (!normalizedDeviceId) {
    if (mode === 'log') {
      return {
        ok: true,
        deviceBound: false,
        deviceRequired: true,
        deviceHash: '',
        clientApp: clientApp
      };
    }
    return {ok: false, status: 'error', message: 'device_required'};
  }

  var deviceHash = _hashDeviceId_(normalizedDeviceId);
  if (!deviceHash) {
    return {ok: false, status: 'error', message: 'device_binding_not_configured'};
  }

  var sheet = _deviceBindingsSheet_();
  var row = _findBindingRow_(sheet, normalizedUserId);
  var now = new Date();

  if (!row) {
    if (readOnly) return {ok: false, status: 'error', message: 'device_binding_not_ready'};
    sheet.appendRow([
      normalizedUserId, deviceHash, clientApp, now, now,
      'ACTIVE', 0, ''
    ]);
    return {
      ok: true,
      deviceBound: true,
      firstBind: true,
      deviceHash: deviceHash,
      clientApp: clientApp
    };
  }

  var values = sheet.getRange(row, 1, 1, DEVICE_BINDING_HEADERS.length).getValues()[0];
  var currentHash = String(values[1] || '').trim();
  var status = String(values[5] || 'ACTIVE').trim().toUpperCase() || 'ACTIVE';
  var resetState = status === 'RESET' || !currentHash;

  if (resetState) {
    if (readOnly) return {ok: false, status: 'error', message: 'device_binding_not_ready'};
    sheet.getRange(row, 2, 1, 6).setValues([[
      deviceHash, clientApp, values[3] || now, now, 'ACTIVE',
      Number(values[6] || 0)
    ]]);
    return {
      ok: true,
      deviceBound: true,
      firstBind: true,
      deviceHash: deviceHash,
      clientApp: clientApp
    };
  }

  if (currentHash !== deviceHash) {
    if (mode === 'log') {
      if (!readOnly) sheet.getRange(row, 5).setValue(now);
      return {
        ok: true,
        deviceBound: true,
        deviceMismatch: true,
        deviceHash: deviceHash,
        clientApp: clientApp
      };
    }
    return {ok: false, status: 'error', message: 'device_mismatch'};
  }

  if (!readOnly) {
    sheet.getRange(row, 3).setValue(clientApp);
    sheet.getRange(row, 5).setValue(now);
  }
  return {
    ok: true,
    deviceBound: true,
    firstBind: false,
    deviceHash: deviceHash,
    clientApp: clientApp
  };
}

function _findSessionRow_(sheet, sessionHash) {
  if (!sessionHash || sheet.getLastRow() < 2) return 0;
  var values = sheet.getRange(2, 1, sheet.getLastRow() - 1, 1).getValues();
  for (var i = 0; i < values.length; i++) {
    if (String(values[i][0] || '').trim() === sessionHash) return i + 2;
  }
  return 0;
}

function _revokeMemberSessions_(userId) {
  var sheet = _authSessionsSheet_();
  if (sheet.getLastRow() < 2) return 0;
  var target = _normalizeBindingUserId_(userId);
  var values = sheet.getRange(2, 1, sheet.getLastRow() - 1, AUTH_SESSION_HEADERS.length).getValues();
  var count = 0;
  var now = new Date();
  for (var i = 0; i < values.length; i++) {
    if (_normalizeBindingUserId_(values[i][1]) !== target) continue;
    if (String(values[i][6] || '').toUpperCase() === 'REVOKED') continue;
    sheet.getRange(i + 2, 7, 1, 2).setValues([['REVOKED', now]]);
    count++;
  }
  return count;
}

// Same effect as calling _revokeMemberSessions_ once per userId, but reads
// and writes the sessions sheet exactly once regardless of how many userIds
// are passed in. getMembers() used to call the single-user version in a loop
// for every non-active member row, which meant one full sessions-sheet scan
// (plus a per-match write) per such row on every getMembers() call — as the
// Members sheet grew this made getMembers() slow enough to blow past the
// bot's request timeout and fail-close real active members out of /renew.
function _revokeMemberSessionsBulk_(userIds) {
  if (!userIds || !userIds.length) return 0;
  var targets = {};
  for (var t = 0; t < userIds.length; t++) {
    targets[_normalizeBindingUserId_(userIds[t])] = true;
  }
  var sheet = _authSessionsSheet_();
  if (sheet.getLastRow() < 2) return 0;
  var range  = sheet.getRange(2, 1, sheet.getLastRow() - 1, AUTH_SESSION_HEADERS.length);
  var values = range.getValues();
  var now = new Date();
  var count = 0;
  for (var i = 0; i < values.length; i++) {
    if (!targets[_normalizeBindingUserId_(values[i][1])]) continue;
    if (String(values[i][6] || '').toUpperCase() === 'REVOKED') continue;
    values[i][6] = 'REVOKED';
    values[i][7] = now;
    count++;
  }
  if (count) range.setValues(values);
  return count;
}

// One full read of the sessions sheet, returning {userId: mostRecentLastSeenAt}
// for every user who has ever logged into the Web App. LastSeenAt is set at
// session creation and bumped on every subsequent token verification, so a
// missing entry means that user has never used the Web App at all — used by
// getMembers() to flag Premium members worth reminding to log in.
function _lastActiveByUser_() {
  var sheet = _authSessionsSheet_();
  var result = {};
  if (sheet.getLastRow() < 2) return result;
  var values = sheet.getRange(2, 1, sheet.getLastRow() - 1, AUTH_SESSION_HEADERS.length).getValues();
  for (var i = 0; i < values.length; i++) {
    var userId   = _normalizeBindingUserId_(values[i][1]);
    var lastSeen = values[i][8];
    if (!userId || !lastSeen) continue;
    var seenDate = lastSeen instanceof Date ? lastSeen : new Date(lastSeen);
    if (isNaN(seenDate.getTime())) continue;
    if (!result[userId] || seenDate > result[userId]) {
      result[userId] = seenDate;
    }
  }
  return result;
}

function _createAuthSession_(token, userId, deviceCheck, expireDate) {
  var sessionHash = _hashSessionToken_(token);
  if (!sessionHash) return {status: 'error', message: 'device_binding_not_configured'};
  var sheet = _authSessionsSheet_();
  var now = new Date();
  sheet.appendRow([
    sessionHash,
    _normalizeBindingUserId_(userId),
    deviceCheck.deviceHash || '',
    deviceCheck.clientApp || 'web',
    now,
    expireDate || '',
    'ACTIVE',
    '',
    now
  ]);
  return {status: 'ok'};
}

function _verifyAuthSession_(token, userId, deviceCheck, expireDate, options) {
  var readOnly = !!(options && options.readOnly);
  var sessionHash = _hashSessionToken_(token);
  if (!sessionHash) return {status: 'error', message: 'device_binding_not_configured'};
  var sheet = _authSessionsSheet_();
  var row = _findSessionRow_(sheet, sessionHash);
  var now = new Date();

  // A token issued before Approach B is migrated on its first valid request.
  if (!row) {
    if (readOnly) return {status: 'error', message: 'auth_session_not_ready'};
    var created = _createAuthSession_(token, userId, deviceCheck, expireDate);
    if (created.status !== 'ok') return created;
    return {status: 'ok', migrated: true};
  }

  var values = sheet.getRange(row, 1, 1, AUTH_SESSION_HEADERS.length).getValues()[0];
  var status = String(values[6] || '').trim().toUpperCase();
  if (status !== 'ACTIVE') {
    return {status: 'error', message: status === 'EXPIRED' ? 'expired' : 'invalid_token'};
  }

  var sessionExpire = values[5] instanceof Date ? values[5] : _parseMemberDate(values[5]);
  if (sessionExpire && sessionExpire < now) {
    if (!readOnly) sheet.getRange(row, 7, 1, 2).setValues([['EXPIRED', now]]);
    return {status: 'error', message: 'expired'};
  }

  var storedUserId = _normalizeBindingUserId_(values[1]);
  if (storedUserId !== _normalizeBindingUserId_(userId)) {
    return {status: 'error', message: 'member_mismatch'};
  }

  var storedDeviceHash = String(values[2] || '').trim();
  if (storedDeviceHash !== String(deviceCheck.deviceHash || '')) {
    if (_deviceBindingMode_() === 'log') {
      if (!readOnly) sheet.getRange(row, 9).setValue(now);
      return {status: 'ok', deviceMismatch: true};
    }
    return {status: 'error', message: 'device_mismatch'};
  }

  if (!readOnly) sheet.getRange(row, 9).setValue(now);
  return {status: 'ok'};
}

function resetMemberDevice(userId) {
  var members = SpreadsheetApp.openById(SS_ID).getSheetByName(MEMBERS);
  var target = _normalizeBindingUserId_(userId);
  if (!members || !_findMemberRowByUserId_(members, target)) {
    return {status: 'error', message: 'member_not_found'};
  }

  var sheet = _deviceBindingsSheet_();
  var row = _findBindingRow_(sheet, target);
  var now = new Date();
  if (!row) {
    sheet.appendRow([target, '', 'web', '', now, 'RESET', 1, now]);
  } else {
    var count = Number(sheet.getRange(row, 7).getValue() || 0) + 1;
    sheet.getRange(row, 2, 1, 7).setValues([['', 'web', '', now, 'RESET', count, now]]);
  }
  _revokeMemberSessions_(target);
  return {status: 'ok', message: 'device_reset'};
}
