// ═══════════════════════════════════════════════════════════
//  JAN JAPAN Auction — Apps Script (Code.gs)
//  Members Sheet Columns:
//  [0] UserID  [1] Username  [2] StartDate  [3] ExpireDate
//  [4] Status  [5] CancelCount  [6] Password  [7] Package  [8] Token
//  Columns A-I above are a load-bearing contract read/written by the
//  Telegram bot, patch files, and this script positionally — never
//  reorder or repurpose them. New fields are appended after [8] only.
//  [9] (J) is reserved and left untouched: it carries "DeviceID" from the
//  retired Approach-A device-binding patch (see
//  apps-script/APPROACH_B_DEPLOYMENT.md: "Do not add DeviceID to Members" /
//  "Do not copy the old J-column patch") -- current device binding lives in
//  the separate DeviceBindings/AuthSessions sheets instead, but column J's
//  old label and data are left alone rather than silently repurposed.
//  [10] GoogleSub  [11] GoogleEmail — JACC Google Login (website-only
//  signup path for members who never touch Telegram). A row with
//  Status "PENDING" is a Google-authenticated identity that has not
//  completed its first payment yet: Package is pre-set to "WEB" (the
//  only package this signup path issues) but ExpireDate is empty, so
//  it must never be treated as an active/expired member by the usual
//  ExpireDate-based date math until an admin approval sets a real
//  ExpireDate and status. It does, however, expire on its own after
//  PENDING_SIGNUP_EXPIRY_DAYS with no payment (measured from StartDate) --
//  see _isPendingSignupExpired_.
// ═══════════════════════════════════════════════════════════

var SS_ID    = "1ZRw9xUS2pqZe5rJdmBtsX6yS7hAc65BHDO6K3zG1mpY";
var MEMBERS  = "Members";
var LOG_SHEET = "ID_Change_Log";
var PAY_SHEET = "Payment_History";
var FINANCE_SHEET = "Finance";

// Column indexes (0-based)
var C_USERID   = 0;
var C_USERNAME = 1;
var C_START    = 2;
var C_EXPIRE   = 3;
var C_STATUS   = 4;
var C_CANCELCOUNT = 5;
var C_PASSWORD = 6;
var C_PACKAGE  = 7;
var C_TOKEN    = 8;
// Column 9 (J) is intentionally skipped -- see the header comment above.
var C_GOOGLE_SUB   = 10;
var C_GOOGLE_EMAIL = 11;

var MEMBER_STATUS_PENDING = "PENDING";
// A Google Login signup that never completes its first payment sits in
// PENDING with a live session token indefinitely otherwise. After this many
// days from StartDate with no admin approval, getMembers()/verifyToken()
// stop treating the row as a valid live session (EXPIRED, token revoked) --
// but verifyGoogleLogin() always lets the same Google account sign back in
// and refreshes StartDate, so nobody is ever permanently locked out, they
// just need to re-authenticate with Google after being idle this long.
var PENDING_SIGNUP_EXPIRY_DAYS = 14;

function _isPendingSignupExpired_(startDateRaw, now) {
  var startDate = _parseMemberDate(startDateRaw);
  if (!startDate) return false;
  var deadline = new Date(startDate.getTime());
  deadline.setDate(deadline.getDate() + PENDING_SIGNUP_EXPIRY_DAYS);
  return now > deadline;
}

// ── doGet — Price Data ─────────────────────────────────────
function doGet(e) {
  try {
    var sheet = SpreadsheetApp.openById(SS_ID).getSheetByName("Sheet1");
    var rows   = sheet.getDataRange().getValues();
    var data   = [];
    for (var i = 1; i < rows.length; i++) {
      var row = rows[i];
      if (!row[1]) continue;

      var dateVal = row[0];
      var dateStr = (dateVal instanceof Date)
        ? Utilities.formatDate(dateVal, "Asia/Bangkok", "dd/MM/yyyy")
        : String(dateVal);

      data.push({
        date:      dateStr,
        chassis:   String(row[1] || ""),
        model:     String(row[2] || "UNKNOWN"),
        color:     String(row[3] || "-"),
        year:      parseInt(row[4]) || 0,
        price:     parseFloat(row[5]) || 0,
        location:  String(row[6] || ""),
        addedBy:   String(row[7] || ""),
        image_url: String(row[8] || "")
      });
    }

    return ContentService
      .createTextOutput(JSON.stringify({status:"ok", data:data}))
      .setMimeType(ContentService.MimeType.JSON);
  } catch(err) {
    return ContentService
      .createTextOutput(JSON.stringify({status:"error", message:err.toString()}))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

// ── doPost — All Actions ───────────────────────────────────
function doPost(e) {
  var lock = LockService.getScriptLock();
  var lockHeld = false;
  try {
    lock.waitLock(30000);
    lockHeld = true;
    var ss   = SpreadsheetApp.openById(SS_ID);
    var data = JSON.parse(e.postData.contents);
    var payload = data;

    switch (data.action) {

      // ── Save / Update Member ─────────────────────────────
      case "saveMember":
        var saveMemberAuth = _authorizeFinanceReport_(data.serverKey);
        if (saveMemberAuth) return _json(saveMemberAuth);
        return _json(saveMember(
          data.userId, data.username, data.days,
          data.password || "", data.package || "CH"
        ));

      // ── Get Members List ─────────────────────────────────
      case "getMembers":
        var getMembersAuth = _authorizeFinanceReport_(data.serverKey);
        if (getMembersAuth) return _json(getMembersAuth);
        return _json({status:"ok", members: getMembers()});

      // ── Verify Login (Password → Token) ─────────────────
      case "validateLogin":
      case "verifyLogin":
        var loginResult = verifyLogin(data.password, data.deviceId, data.app);
        writeAuditLog(
          loginResult.username || "Unknown",
          "LOGIN",
          "WebApp",
          loginResult.status === "ok" ? "SUCCESS" : "FAIL:" + (loginResult.message || "")
        );
        return _json(loginResult);

      // ── Verify Token (on page load) ──────────────────────
      case "verifyToken":
        return _json(verifyToken(data.token, data.deviceId, data.app, data.userId));

      // ── Verify Google Login (Google ID token → Token) ────
      // Website-only signup path: no Telegram identity involved. See the
      // Members-sheet header comment and verifyGoogleLogin() for the
      // PENDING/synthetic-userId design this depends on.
      case "verifyGoogleLogin":
        var googleLoginResult = verifyGoogleLogin(data.idToken, data.deviceId, data.app);
        writeAuditLog(
          googleLoginResult.username || "Unknown",
          "GOOGLE_LOGIN",
          "WebApp",
          googleLoginResult.status === "ok" ? "SUCCESS" : "FAIL:" + (googleLoginResult.message || "")
        );
        return _json(googleLoginResult);

      // ── Admin-only Device Reset ──────────────────────────
      case "resetMemberDevice":
        var resetDeviceAuth = _authorizeFinanceReport_(data.serverKey);
        if (resetDeviceAuth) return _json(resetDeviceAuth);
        return _json(resetMemberDevice(data.userId));

      // ── Get Password by UserID ───────────────────────────
      case "getPassword":
        var getPasswordAuth = _authorizeFinanceReport_(data.serverKey);
        if (getPasswordAuth) return _json(getPasswordAuth);
        return _json(getPassword(data.userId));

      // ── Reset Password ───────────────────────────────────
      case "resetPassword":
        var resetPasswordAuth = _authorizeFinanceReport_(data.serverKey);
        if (resetPasswordAuth) return _json(resetPasswordAuth);
        return _json(resetPassword(data.username, data.password));

      // ── Update Member Telegram ID ────────────────────────
      case "updateMemberId":
        var updateMemberIdAuth = _authorizeFinanceReport_(data.serverKey);
        if (updateMemberIdAuth) return _json(updateMemberIdAuth);
        return _json(updateMemberId(data.username, data.newId, data.password));

      // ── Backup CSV ───────────────────────────────────────
      case "getBackupCSV":
        var getBackupCSVAuth = _authorizeFinanceReport_(data.serverKey);
        if (getBackupCSVAuth) return _json(getBackupCSVAuth);
        return _json(getBackupCSV());// ── Get Cars Count ─────────────────────────
      case "getCarsCount":
        var gcSheet = ss.getSheetByName("Sheet1");
        if (!gcSheet) return _json({count: 0});
        return _json({count: gcSheet.getLastRow() - 1});
        // —— Update Car (Price / Color / Model) ————
      case "updateCar":
        var updateCarAuth = _authorizeFinanceReport_(data.serverKey);
        if (updateCarAuth) return _json(updateCarAuth);
        var uc_sheet   = ss.getSheetByName("Sheet1");
        var uc_field   = data.field;
        var uc_chassis = data.chassis;
        var uc_value   = data.value;
        var fieldMap   = { "price":"Price", "color":"Color", "model":"Model" };
        var colName    = fieldMap[uc_field];
        if (!colName) return _json({status:"error", msg:"Invalid field"});
        var uc_headers = uc_sheet.getRange(1,1,1,uc_sheet.getLastColumn()).getValues()[0];
        var uc_col     = uc_headers.indexOf(colName) + 1;
        var uc_chCol   = uc_headers.indexOf("Chassis") + 1;
        var uc_rows    = uc_sheet.getRange(2,uc_chCol,uc_sheet.getLastRow()-1,1).getValues();
        var uc_row     = -1;
        for (var i = 0; i < uc_rows.length; i++) {
          if (uc_rows[i][0].toString().toUpperCase() === uc_chassis.toUpperCase()) {
            uc_row = i + 2; break;
          }
        }
        if (uc_row === -1) return _json({status:"error", msg:"Chassis not found"});
        uc_sheet.getRange(uc_row, uc_col).setValue(uc_value);
        writeAuditLog('Admin', 'CAR_EDIT:' + uc_field, uc_chassis, uc_value);
        return _json({status:"ok"});
// —— Promo Code Redeem ————————————————————
 case "redeemPromo":
  var promoSheet = ss.getSheetByName("Promos");
  if (!promoSheet) return _json({status:"error", msg:"no_sheet"});
  var pCode   = data.code.toString().toUpperCase();
  var pUserId = String(data.userId);
  var pRows   = promoSheet.getDataRange().getValues();

  for (var pi = 1; pi < pRows.length; pi++) {
    if (pRows[pi][0].toString().toUpperCase() !== pCode) continue;

    var pUsed = pRows[pi][1] ? pRows[pi][1].toString().split(",").filter(Boolean) : [];
    var pMax  = parseInt(pRows[pi][2]) || 40;
    var pDays = parseInt(pRows[pi][3]) || 30;
    var pPkg  = String(pRows[pi][4] || 'WEB').trim().toUpperCase();

    if (pUsed.includes(pUserId))
      return _json({status:"error", msg:"already_used"});

    if (pUsed.length >= pMax)
      return _json({status:"error", msg:"max_reached", used:pUsed.length, max:pMax});

    pUsed.push(pUserId);
    promoSheet.getRange(pi+1, 2).setValue(pUsed.join(","));
    return _json({status:"ok", days:pDays, used:pUsed.length, max:pMax, package:pPkg});
  }
  return _json({status:"error", msg:"invalid_code"});
        












  






      // —— Promo Stats ————————————————————————
      case "promoStats":
        var psSheet = ss.getSheetByName("Promos");
        var psRows  = psSheet ? psSheet.getDataRange().getValues() : [];
        var psData  = [];
        for (var pj = 1; pj < psRows.length; pj++) {
          var psUsed = psRows[pj][1] ? psRows[pj][1].toString().split(",").filter(Boolean) : [];
          psData.push({code:psRows[pj][0], used:psUsed.length,
                       max:parseInt(psRows[pj][2])||40, days:parseInt(psRows[pj][3])||30});
        }
        return _json({status:"ok", stats:psData});// ── Verify Old ID // ── Update Member Status ──────────────────────────
      case "updateStatus":
        var updateStatusAuth = _authorizeFinanceReport_(data.serverKey);
        if (updateStatusAuth) return _json(updateStatusAuth);
        var usSheet = ss.getSheetByName("Members");
        if (!usSheet) return _json({status:"error", msg:"no_sheet"});
        var usId     = String(data.userId || "");
        var usStatus = String(data.status || "KICKED");
        var usRows   = usSheet.getDataRange().getValues();
        for (var ui = 1; ui < usRows.length; ui++) {
        if (String(usRows[ui][0]) === usId) {
        usSheet.getRange(ui + 1, 5).setValue(usStatus);
        writeAuditLog('Admin', usStatus === 'KICKED' ? 'KICK' : 'ACTIVATE', 'UserID:' + usId, 'SUCCESS');
        return _json({status:'ok', userId: usId, newStatus: usStatus});
      }
         
      
    
        
       
        }
        return _json({status:"error", msg:"not_found"});
      case "verifyOId":
        var voSheet = ss.getSheetByName("Members");
        if (!voSheet) return _json({status:"error", msg:"no_sheet"});
        var voUsername = (data.username || "").toString().toLowerCase().replace("@","");
        var voOldId    = String(data.oldId || "");
        var voRows     = voSheet.getDataRange().getValues();
        for (var vi = 1; vi < voRows.length; vi++) {
          var rowUser = (voRows[vi][1] || "").toString().toLowerCase().replace("@","");
          var rowId   = String(voRows[vi][0] || "");
          if (rowUser === voUsername && rowId === voOldId) {
            return _json({status:"ok", row: vi+1});
          }
        }
        return _json({status:"error", msg:"not_found"});

      // ── Log Payment to Finance Sheet ───────────────
      case "logPayment":
        var finSheet = ss.getSheetByName(FINANCE_SHEET);
        if (!finSheet) finSheet = ss.insertSheet(FINANCE_SHEET);
        _ensureFinanceHeaders_(finSheet);
        var fp = data.payment || {};
        var paymentId = String(fp.paymentId || fp.transactionNo || "").trim();
        if (paymentId.toUpperCase() === "UNKNOWN") paymentId = "";
        if (paymentId) {
          var existingFinanceRows = finSheet.getDataRange().getValues();
          for (var ei = 1; ei < existingFinanceRows.length; ei++) {
            var existingTransaction = String(existingFinanceRows[ei][8] || "").trim();
            var existingPaymentId = String(existingFinanceRows[ei][14] || "").trim();
            if (existingTransaction === paymentId || existingPaymentId === paymentId) {
              return _json({status:"ok", result:"duplicate", duplicate:true});
            }
          }
        }
        finSheet.appendRow([
          fp.date || "", fp.time || "", fp.userId || "",
          fp.username || "", fp.package || "", fp.months || "",
          fp.amount || "", fp.payType || fp.method || "", fp.transactionNo || "",
          fp.receiver || fp.transferTo || "", fp.sender || "", fp.status || "APPROVED",
          fp.entryType || "", fp.source || "PAYMENT_SLIP", fp.paymentId || "",
          fp.approvedBy || "", fp.expireDate || "", fp.note || ""
        ]);
        return _json({status:"ok"});

      // ── Locked Member + Finance approval transaction ──
      case "approvePaymentTransaction":
        var approvalAuth = _authorizeFinanceReport_(data.serverKey);
        if (approvalAuth) return _json(approvalAuth);
        return _json(approvePaymentTransaction_(data.payment || data));

      // ── Locked manual member + Finance approval transaction ──
      case "approveManualMember":
        var manualApprovalAuth = _authorizeFinanceReport_(data.serverKey);
        if (manualApprovalAuth) return _json(manualApprovalAuth);
        return _json(approveManualMemberTransaction_(data.payment || data));

      // ── Inspect one protected payment transaction safely ──
      case "inspectPaymentTransaction":
        var inspectAuth = _authorizeFinanceReport_(data.serverKey);
        if (inspectAuth) return _json(inspectAuth);
        return _json(inspectPaymentTransaction_(data.payment || data));

      // ── Durable Telegram payment draft recovery ─────────────
      case "savePaymentDraft":
        var draftSaveAuth = _authorizeFinanceReport_(data.serverKey);
        if (draftSaveAuth) return _json(draftSaveAuth);
        return _json(_savePaymentDraft_(data.draft || data));
      case "getPaymentDraft":
        var draftGetAuth = _authorizeFinanceReport_(data.serverKey);
        if (draftGetAuth) return _json(draftGetAuth);
        return _json(_getPaymentDraft_(data.draft || data));
      case "clearPaymentDraft":
        var draftClearAuth = _authorizeFinanceReport_(data.serverKey);
        if (draftClearAuth) return _json(draftClearAuth);
        return _json(_clearPaymentDraft_(data.draft || data));

      // ── Admin Finance Summary ───────────────────────
      case "getFinanceReport":
        var financeAuth = _authorizeFinanceReport_(data.serverKey);
        if (financeAuth) return _json(financeAuth);
        return _json(getFinanceReport_(data.month));
      case "getBrokers":
        var gbSheet = ss.getSheetByName("Brokers");
        if (!gbSheet) return _json({status:"ok", brokers:[]});
        var gbRows = gbSheet.getDataRange().getValues();
        var brokers = [];
        for (var gi = 1; gi < gbRows.length; gi++) {
          var r = gbRows[gi];
          brokers.push({
            brokerId:     String(r[0]||""),
            telegramId:   String(r[1]||""),
            username:     String(r[2]||""),
            status:       String(r[3]||"FREE"),
            rating:       Number(r[4]||0),
            deals:        Number(r[5]||0),
            rating1Count: Number(r[6]||0),
            joinDate:     String(r[7]||""),
            declineCount: Number(r[8]||0)
          })
        }
        return _json({status:"ok", brokers:brokers});

      // ── Add Broker ───────────────────────────────────
      case "addBroker":
        var abSheet = ss.getSheetByName("Brokers");
        if (!abSheet) {
          abSheet = ss.insertSheet("Brokers");
          abSheet.appendRow([
            "BrokerID","TelegramID","Username","Status",
            "Rating","Deals","Rating1Count","JoinDate","DeclineCount"
          ]),
          abSheet.getRange(1,1,1,8).setFontWeight("bold")
            .setBackground("#1A2535").setFontColor("#FFFFFF");
        }
        var ab = data;
        abSheet.appendRow([
          ab.brokerId   || "",
          ab.telegramId || "",
          ab.username   || "",
          "FREE", 0, 0, 0,
          Utilities.formatDate(new Date(),"Asia/Bangkok","dd/MM/yyyy")
        ]);
        return _json({status:"ok"});

      // ── Update Broker ─────────────────────────────────
      case "updateBroker":
        var ubSheet = ss.getSheetByName("Brokers");
        if (!ubSheet) return _json({status:"error",msg:"no_sheet"});
        var ubId   = String(data.telegramId||"");
        var ubRows = ubSheet.getDataRange().getValues();
        for (var ubi = 1; ubi < ubRows.length; ubi++) {
          if (String(ubRows[ubi][1]) === ubId) {
            if (data.status      !== undefined)
              ubSheet.getRange(ubi+1,4).setValue(data.status);
            if (data.rating      !== undefined)
              ubSheet.getRange(ubi+1,5).setValue(data.rating);
            if (data.deals       !== undefined)
              ubSheet.getRange(ubi+1,6).setValue(data.deals);
            if (data.rating1Count !== undefined)
              ubSheet.getRange(ubi+1,7).setValue(data.rating1Count);
             if (data.declineCount !== undefined)
             ubSheet.getRange(ubi+1,9).setValue(data.declineCount); 
            return _json({status:"ok"});
          }
        }
        return _json({status:"error",msg:"not_found"});
       // — Increment Decline Count ————————————
case "incrementDecline":
  var idSheet = ss.getSheetByName("Brokers");
  if (!idSheet) return _json({status:"error"});
  var idRows = idSheet.getDataRange().getValues();
  for (var ii = 1; ii < idRows.length; ii++) {
    if (String(idRows[ii][1]) === String(data.telegramId)) {
      var cur = Number(idRows[ii][8]||0);
      idSheet.getRange(ii+1, 9).setValue(cur + 1);
      return _json({status:"ok", declineCount: cur+1});
    }
  }
  return _json({status:"error", msg:"not_found"});
      // ── Add Request ───────────────────────────────────
      case "addRequest":
        var arSheet = ss.getSheetByName("Requests");
        if (!arSheet) {
          arSheet = ss.insertSheet("Requests");
          arSheet.appendRow([
            "ReqID","CustomerID","Username","CarType",
            "Budget","Year","Grade","Condition",
            "Timeline","Status","BrokerID","CreatedDate"
          ]);
          arSheet.getRange(1,1,1,12).setFontWeight("bold")
            .setBackground("#1A2535").setFontColor("#FFFFFF");
        }
        var ar = data;
        var arCustomerId = String(ar.customerId || "").replace(/[\u0000-\u001F\u007F\u200B-\u200D\u2060\uFEFF]/g, "").trim();
        var arUsername = String(ar.username || "").replace(/[\u0000-\u001F\u007F\u200B-\u200D\u2060\uFEFF]/g, "").trim();
        if (!/^\d+$/.test(arCustomerId)) return _json({status:"error", msg:"customer_id_required"});
        if (!arUsername) return _json({status:"error", msg:"username_required"});

        var requestedReqId = _normalizeRequestId_(ar.reqId);
        var requestIdRegenerated = false;
        if (requestedReqId && !_validRequestId_(requestedReqId)) {
          requestedReqId = "";
          requestIdRegenerated = true;
        }
        if (requestedReqId && _requestIdExists_(arSheet, requestedReqId)) {
          requestedReqId = "";
          requestIdRegenerated = true;
        }
        var requestPrefix = String(ar.carType || "").trim().toUpperCase() === "AUCTION" ? "A" : "R";
        var storedReqId = requestedReqId || _newRequestId_(arSheet, requestPrefix);
        var createdDate = Utilities.formatDate(new Date(),"Asia/Bangkok","dd/MM/yyyy HH:mm");
        arSheet.appendRow([
          storedReqId,
          arCustomerId,
          arUsername,
          ar.carType    || "",
          ar.budget     || "",
          ar.year       || "",
          ar.grade      || "",
          ar.condition  || "",
          ar.timeline   || "",
          "OPEN", "", createdDate
        ]);
        return _json({status:"ok", reqId:storedReqId, customerId:arCustomerId, username:arUsername, createdDate:createdDate, requestIdRegenerated:requestIdRegenerated});

      // ── Update Request ────────────────────────────────
      case "updateRequest":
        var urSheet = ss.getSheetByName("Requests");
        if (!urSheet) return _json({status:"error",msg:"no_sheet"});
        var urId   = _normalizeRequestId_(data.reqId);
        var urOwnerId = String(data.customerId || "").trim();
        var urRows = urSheet.getDataRange().getValues();
        for (var uri = 1; uri < urRows.length; uri++) {
          if (_normalizeRequestId_(urRows[uri][0]) !== urId) continue;
          if (urOwnerId && String(urRows[uri][1] || "").trim() !== urOwnerId) {
            return _json({status:"error",msg:"request_owner_mismatch"});
          }
          if (data.status   !== undefined)
            urSheet.getRange(uri+1,10).setValue(String(data.status || "").trim().toUpperCase());
          if (data.brokerId !== undefined)
            urSheet.getRange(uri+1,11).setValue(String(data.brokerId || "").trim());
          return _json({status:"ok", reqId:urId, customerId:String(urRows[uri][1] || "")});
        }
        return _json({status:"error",msg:"not_found"});      // ── Get Request ──────────────────────────────
      case "getRequest":
        var grSheet = ss.getSheetByName("Requests");
        if (!grSheet) return _json({status:"error",msg:"no_sheet"});
        var grId   = _normalizeRequestId_(data.reqId);
        var grOwnerId = String(data.customerId || "").trim();
        var grRows = grSheet.getDataRange().getValues();
        for (var gri = 1; gri < grRows.length; gri++) {
          if (_normalizeRequestId_(grRows[gri][0]) !== grId) continue;
          if (grOwnerId && String(grRows[gri][1] || "").trim() !== grOwnerId) {
            return _json({status:"error",msg:"request_owner_mismatch"});
          }
          return _json({
            status:     "ok",
            reqId:      String(grRows[gri][0]),
            customerId: String(grRows[gri][1]),
            username:   String(grRows[gri][2]),
            carType:    String(grRows[gri][3]),
            budget:     String(grRows[gri][4]),
            year:       String(grRows[gri][5]),
            grade:      String(grRows[gri][6]),
            condition:  String(grRows[gri][7]),
            timeline:   String(grRows[gri][8]),
            reqStatus:  String(grRows[gri][9]),
          });
        }
        return _json({status:"error",msg:"not_found"});  // ════════════════════════════════════════════════════════
// DEPOSIT FLOW — Code.gs ADDITIONS
// "// ── Price Data (POST)" comment အပေါ်မှာ ထည့်ပါ
// ════════════════════════════════════════════════════════

case 'saveDeposit': {
  const ss = SpreadsheetApp.openById(SS_ID);
  let depSheet = ss.getSheetByName('Deposits');
  if (!depSheet) {
    depSheet = ss.insertSheet('Deposits');
    depSheet.appendRow([
      'ReqId','CustomerId','BrokerTgId',
      'THB_Amount','MMK_Amount','MMK_Rate',
      'Date','TxnNo','PayType','Status','AuctionResult','CarPrice'
    ]);
  }

  const {
    reqId, customerId, brokerTgId,
    thbAmount, mmkAmount, mmkRate,
    date, txnNo, payType
  } = payload;

  depSheet.appendRow([
    reqId, customerId, brokerTgId,
    thbAmount, mmkAmount, mmkRate,
    date, txnNo, payType,
    'HOLD', '', ''
  ]);

  return _json({ status: 'ok' });
}

case 'getDeposit': {
  const ss = SpreadsheetApp.openById(SS_ID);
  const depSheet = ss.getSheetByName('Deposits');
  if (!depSheet) return _json({ status: 'error', msg: 'no_sheet' });

  const data    = depSheet.getDataRange().getValues();
  const headers = data[0];
  const reqIdx  = headers.indexOf('ReqId');
  const cidIdx  = headers.indexOf('CustomerId');
  const bidIdx  = headers.indexOf('BrokerTgId');
  const thbIdx  = headers.indexOf('THB_Amount');
  const mmkIdx  = headers.indexOf('MMK_Amount');
  const rateIdx = headers.indexOf('MMK_Rate');
  const statIdx = headers.indexOf('Status');

  for (let i = 1; i < data.length; i++) {
    if (data[i][reqIdx] == payload.reqId) {
      return _json({
        status:      'ok',
        reqId:       data[i][reqIdx],
        customerId:  String(data[i][cidIdx]),
        brokerTgId:  String(data[i][bidIdx]),
        thbAmount:   data[i][thbIdx],
        mmkAmount:   data[i][mmkIdx],
        mmkRate:     data[i][rateIdx],
        depositStatus: data[i][statIdx],
      });
    }
  }
  return _json({ status: 'error', msg: 'not_found' });
}

case 'updateDeposit': {
  const ss = SpreadsheetApp.openById(SS_ID);
  const depSheet = ss.getSheetByName('Deposits');
  if (!depSheet) return _json({ status: 'error', msg: 'no_sheet' });

  const data      = depSheet.getDataRange().getValues();
  const headers   = data[0];
  const reqIdx    = headers.indexOf('ReqId');
  const statIdx   = headers.indexOf('Status');
  const resIdx    = headers.indexOf('AuctionResult');
  const priceIdx  = headers.indexOf('CarPrice');

  for (let i = 1; i < data.length; i++) {
    if (data[i][reqIdx] == payload.reqId) {
      // AuctionResult update
      if (payload.auctionResult) {
        depSheet.getRange(i + 1, resIdx + 1).setValue(payload.auctionResult);

        // Status update
        if (payload.auctionResult === 'WON') {
          depSheet.getRange(i + 1, statIdx + 1).setValue('WON');
        } else if (payload.auctionResult === 'LOST') {
          depSheet.getRange(i + 1, statIdx + 1).setValue('LOST');
        } else if (payload.auctionResult === 'REFUNDED') {
          depSheet.getRange(i + 1, statIdx + 1).setValue('REFUNDED');
        }
      }
      // CarPrice update
      if (payload.carPrice && priceIdx >= 0) {
        depSheet.getRange(i + 1, priceIdx + 1).setValue(payload.carPrice);
      }
      return _json({ status: 'ok' });
    }
  }
  return _json({ status: 'error', msg: 'not_found' }); 
  }
  case 'saveRating': {
  const rSs = SpreadsheetApp.openById(SS_ID);
  let rSheet = rSs.getSheetByName('Ratings');
  if (!rSheet) {
    rSheet = rSs.insertSheet('Ratings');
    rSheet.appendRow(['ReqId','BrokerId','CustomerId','Stars','Date']);
  }
  const now2 = Utilities.formatDate(new Date(),'Asia/Bangkok','dd/MM/yyyy HH:mm');
  rSheet.appendRow([payload.reqId, payload.brokerId, payload.customerId, payload.stars, now2]);

  const bSheet2 = rSs.getSheetByName('Brokers');
  if (!bSheet2) return _json({status:'ok', ban:false});
  const bData2 = bSheet2.getDataRange().getValues();
  const bH2 = bData2[0];
  const bidI = bH2.indexOf('BrokerId');
  const rI   = bH2.indexOf('Rating');
  const dI   = bH2.indexOf('Deals');
  const r1I  = bH2.indexOf('Rating1Count');
  const allR = rSheet.getDataRange().getValues();
  const bRatings = allR.slice(1).filter(r=>String(r[1])==String(payload.brokerId)).map(r=>Number(r[3]));
  const avg  = bRatings.length > 0 ? bRatings.reduce((a,b)=>a+b,0)/bRatings.length : 0;
  const one  = bRatings.filter(s=>s===1).length;
  const ban2 = one >= 3;
  for (let i=1; i<bData2.length; i++) {
    if (String(bData2[i][bidI]) == String(payload.brokerId)) {
      if (rI  >= 0) bSheet2.getRange(i+1,rI+1).setValue(avg.toFixed(2));
      if (dI  >= 0) bSheet2.getRange(i+1,dI+1).setValue(bRatings.length);
      if (r1I >= 0) bSheet2.getRange(i+1,r1I+1).setValue(one);
      break;
    }
  }
  return _json({status:'ok', ban:ban2, newRating:avg, oneStarCount:one});
}














































case 'getCancelCount': {
  const ss = SpreadsheetApp.openById(SS_ID);
  const sheet = ss.getSheetByName('Members');
  if (!sheet) return _json({ status: 'error', cancelCount: 0 });

  const rows = sheet.getDataRange().getValues();
  const uid  = String(payload.userId || '');

  for (let i = 1; i < rows.length; i++) {
    if (String(rows[i][0]) === uid) {
      const count = parseInt(rows[i][C_CANCELCOUNT]) || 0;
      return _json({ status: 'ok', cancelCount: count });
    }
  }
  return _json({ status: 'ok', cancelCount: 0 });
}

case 'saveCancelCount': {
  const ss = SpreadsheetApp.openById(SS_ID);
  const sheet = ss.getSheetByName('Members');
  if (!sheet) return _json({ status: 'error', msg: 'no_sheet' });

  const rows    = sheet.getDataRange().getValues();
  const uid     = String(payload.userId || '');
  const newCount = parseInt(payload.cancelCount) || 0;

  for (let i = 1; i < rows.length; i++) {
    if (String(rows[i][0]) === uid) {
      sheet.getRange(i + 1, C_CANCELCOUNT + 1).setValue(newCount);
      return _json({ status: 'ok', cancelCount: newCount });
    }
  }
  return _json({ status: 'error', msg: 'user_not_found' });
}

case 'banCustomer': {
  var banCustomerAuth = _authorizeFinanceReport_(data.serverKey);
  if (banCustomerAuth) return _json(banCustomerAuth);
  const ss = SpreadsheetApp.openById(SS_ID);
  const sheet = ss.getSheetByName('Members');
  if (!sheet) return _json({ status: 'error', msg: 'no_sheet' });

  const rows      = sheet.getDataRange().getValues();
  const uid       = String(payload.userId || '');
  const banExpire = payload.banExpire || '';

  for (let i = 1; i < rows.length; i++) {
    if (String(rows[i][0]) === uid) {
      // Status = BANNED
      sheet.getRange(i + 1, 5).setValue('BANNED');
      // ExpireDate = ban expire date (col 4, index 3, 1-based = 4)
      // Store ban info in the Token column and invalidate any active session.
      sheet.getRange(i + 1, C_TOKEN + 1).setValue('BAN_EXPIRE:' + banExpire);
      _revokeMemberSessions_(uid);
      writeAuditLog('Admin', 'BAN', 'UserID:' + uid, 'expire:' + banExpire);
      return _json({ status: 'ok', banExpire: banExpire });
      
    }
  }
  return _json({ status: 'error', msg: 'user_not_found' });
}
 case 'getData': {
  var tokenResult = _verifyTokenForReadOnlyGetData_(data.token, data.deviceId, data.app, data.userId);
  if (tokenResult.status !== 'ok') {
    return _json({status:'error', msg:tokenResult.message || tokenResult.msg || 'invalid_token'});
  }

  // Authentication and device/session checks remain serialized under the
  // global lock. Release it before the large read-only Sheet1 response so a
  // slow 1.23 MB payload cannot block login, member, or other getData calls.
  if (lockHeld) {
    lock.releaseLock();
    lockHeld = false;
  }

  var gdSheet = ss.getSheetByName('Sheet1');
  if (!gdSheet) return _json({status:'error', msg:'no_sheet'});

  // Read the header and only the requested page. The old implementation used
  // getDataRange().getValues(), which still loaded the entire Sheet1 before
  // returning a small page and could trigger Apps Script response/watchdog
  // failures as the car table grew.
  var gdLastRow = gdSheet.getLastRow();
  var gdLastColumn = gdSheet.getLastColumn();
  var gdOffset = Math.max(0, parseInt(data.offset, 10) || 0);
  var gdLimit = Math.max(0, parseInt(data.limit, 10) || 0);
  if (gdLimit > 500) gdLimit = 500;
  var gdTotal = Math.max(0, gdLastRow - 1);
  if (gdLastRow < 2 || gdLastColumn < 1 || gdOffset >= gdTotal) {
    return _json({status:'ok', cars:[], page:{offset:gdOffset,limit:gdLimit,total:gdTotal,hasMore:false}});
  }

  var gdHeaders = gdSheet.getRange(1, 1, 1, gdLastColumn).getValues()[0]
    .map(function(value){ return String(value || '').trim().toLowerCase(); });
  var gdIndex = function(names, fallback){ for (var hi = 0; hi < names.length; hi++) { var found = gdHeaders.indexOf(String(names[hi]).toLowerCase()); if (found >= 0) return found; } return fallback; };
  var gdEvidence = {
    auctionSheetUrl: gdIndex(['auctionsheeturl','auctionsheet','sheeturl','auction sheet url'], -1),
    auctionGrade: gdIndex(['auctiongrade','grade','auction grade'], -1),
    mileage: gdIndex(['mileage','km','odometer'], -1),
    condition: gdIndex(['condition','damage','condition notes'], -1),
    inspectionStatus: gdIndex(['inspectionstatus','inspection','inspection status'], -1),
    source: gdIndex(['source','sourceurl','source name'], -1),
    sourceDate: gdIndex(['sourcedate','source date','verifiedat'], -1)
  };

  var gdStartRow = 2 + gdOffset;
  var gdAvailableRows = Math.max(0, gdLastRow - gdStartRow + 1);
  var gdReadCount = gdLimit > 0 ? Math.min(gdLimit, gdAvailableRows) : gdAvailableRows;
  var gdRows = gdReadCount > 0
    ? gdSheet.getRange(gdStartRow, 1, gdReadCount, gdLastColumn).getValues()
    : [];
  var gdCars = [];
  for (var gdi = 0; gdi < gdRows.length; gdi++) {
    var r = gdRows[gdi];
    if (!r[0] && !r[1]) continue;
    gdCars.push({
      date:     r[0] ? String(r[0]) : '',
      chassis:  r[1] ? String(r[1]) : '',
      model:    r[2] ? String(r[2]) : '',
      color:    r[3] ? String(r[3]) : '',
      year:     r[4] ? String(r[4]) : '',
      price:    r[5] ? String(r[5]) : '',
      location:  r[6] ? String(r[6]) : '',
      addedBy:   r[7] ? String(r[7]) : '',
      imageUrl:  r[8] ? String(r[8]) : '',
      auctionSheetUrl: gdEvidence.auctionSheetUrl >= 0 ? String(r[gdEvidence.auctionSheetUrl] || '') : '',
      auctionGrade: gdEvidence.auctionGrade >= 0 ? String(r[gdEvidence.auctionGrade] || '') : '',
      mileage: gdEvidence.mileage >= 0 ? String(r[gdEvidence.mileage] || '') : '',
      condition: gdEvidence.condition >= 0 ? String(r[gdEvidence.condition] || '') : '',
      inspectionStatus: gdEvidence.inspectionStatus >= 0 ? String(r[gdEvidence.inspectionStatus] || '') : '',
      source: gdEvidence.source >= 0 ? String(r[gdEvidence.source] || '') : '',
      sourceDate: gdEvidence.sourceDate >= 0 ? String(r[gdEvidence.sourceDate] || '') : ''
    });
  }
  return _json({status:'ok', cars:gdCars, page:{offset:gdOffset,limit:gdLimit,total:gdTotal,hasMore:(gdOffset + gdReadCount) < gdTotal}});
}
case 'removeBroker': {
  var removeBrokerAuth = _authorizeFinanceReport_(data.serverKey);
  if (removeBrokerAuth) return _json(removeBrokerAuth);
  const telegramId = String(payload.telegramId || '').trim();
  if (!telegramId) return _json({ status: 'error', msg: 'telegramId missing' });

  const ss    = SpreadsheetApp.openById(SS_ID);
  const sheet = ss.getSheetByName('Brokers');
  if (!sheet) return _json({ status: 'error', msg: 'Brokers sheet not found' });

  const data = sheet.getDataRange().getValues();
  for (let i = 1; i < data.length; i++) {
    if (String(data[i][0]).trim() === telegramId) {
      sheet.deleteRow(i + 1);
      return _json({ status: 'ok' });
    }
  }
  return _json({ status: 'error', msg: 'broker_not_found' });
}
case 'logVisitor': {
  const ss = SpreadsheetApp.openById(SS_ID);
  let sheet = ss.getSheetByName('Visitors');
  if (!sheet) {
    sheet = ss.insertSheet('Visitors');
    sheet.appendRow(['Date','Time','Country','City','Region','IP']);
    sheet.getRange(1,1,1,6).setFontWeight('bold')
      .setBackground('#1A2535').setFontColor('#FFFFFF');
  }
  const now = Utilities.formatDate(new Date(),'Asia/Bangkok','dd/MM/yyyy');
  const time = Utilities.formatDate(new Date(),'Asia/Bangkok','HH:mm:ss');
  sheet.appendRow([
    now,
    time,
    data.country || '',
    data.city    || '',
    data.region  || '',
    data.ip      || ''
  ]);
  return _json({ status: 'ok' });
}
case "getCompletedOutsideCount": {
  var custId = data.customerId;
  var reqSheet = ss.getSheetByName("Requests");
  var rows = reqSheet.getDataRange().getValues();
  var count = 0;
  for (var i = 1; i < rows.length; i++) {
    if (String(rows[i][1]) === String(custId) &&
        String(rows[i][0]).startsWith("R") &&
        String(rows[i][9]).toUpperCase() === "COMPLETED") {
      count++;
    }
  }
  return ContentService.createTextOutput(
    JSON.stringify({status:"ok", count: count})
  ).setMimeType(ContentService.MimeType.JSON);
}
case "getAuctionCancelCount": {
  var custId = String(data.customerId || '');
  var acSheet = ss.getSheetByName("AuctionCancels");
  if (!acSheet) return _json({status:"ok", banCount:0});
  var rows = acSheet.getDataRange().getValues();
  var banCount = 0;
  for (var i = 1; i < rows.length; i++) {
    if (String(rows[i][0]) === custId) {
      banCount = Number(rows[i][4]) || 0;
      break;
    }
  }
  // အသစ်:
var banStatus = '';
var banExpire = '';
for (var i = 1; i < rows.length; i++) {
  if (String(rows[i][0]) === custId) {
    banCount  = Number(rows[i][4]) || 0;
    banStatus = String(rows[i][5] || '');
    banExpire = String(rows[i][6] || '');
    break;
  }
}
return _json({status:"ok", banCount: banCount, banStatus: banStatus, banExpire: banExpire});
}

case "saveAuctionCancel": {
  var acSheet = ss.getSheetByName("AuctionCancels");
  if (!acSheet) {
    acSheet = ss.insertSheet("AuctionCancels");
    acSheet.appendRow(["CustomerID","Username","ReqId","CancelDate","BanCount","BanStatus","BanExpire"]);
    acSheet.getRange(1,1,1,7).setFontWeight("bold")
      .setBackground("#1A2535").setFontColor("#FFFFFF");
  }
  var now = Utilities.formatDate(new Date(),'Asia/Bangkok','dd/MM/yyyy');
  var custId   = String(data.customerId || '');
  var username = String(data.username || '');
  var reqId    = String(data.reqId || '');
  var banCount = Number(data.banCount || 1);
  var banStatus= String(data.banStatus || '');
  var banExpire= String(data.banExpire || '');

  // existing row update လုပ် မရှိရင် append
  var rows = acSheet.getDataRange().getValues();
  var found = false;
  for (var i = 1; i < rows.length; i++) {
    if (String(rows[i][0]) === custId) {
      acSheet.getRange(i+1,3,1,5).setValues([[reqId, now, banCount, banStatus, banExpire]]);
      found = true; break;
    }
  }
  if (!found) {
    acSheet.appendRow([custId, username, reqId, now, banCount, banStatus, banExpire]);
  }
  return _json({status:"ok"});
}
case 'saveSearchWatch': {
  const watchAuth = _authorizeWebMember_(payload.token, payload.customerId, payload.deviceId, payload.app);
  if (watchAuth) return _json(watchAuth);
  const watchSheet = _getSearchWatchesSheet_();
  const watchFilters = _normalizeWatchFilters_(payload.filters || {});
  const watchUid = String(payload.customerId || '').trim();
  const watchLabel = String(payload.label || 'JACC search alert').trim().slice(0, 120);
  const watchRows = watchSheet.getDataRange().getValues();
  const watchSignature = JSON.stringify(watchFilters);
  for (let wi = 1; wi < watchRows.length; wi++) {
    if (String(watchRows[wi][0]) === watchUid && String(watchRows[wi][4]) === watchSignature) {
      watchSheet.getRange(wi + 1, 6).setValue('ON');
      return _json({status:'ok', watchId:String(watchRows[wi][2]), enabled:true});
    }
  }
  const watchId = 'W' + new Date().getTime().toString(36).toUpperCase();
  watchSheet.appendRow([watchUid, String(payload.username || ''), watchId, watchLabel, watchSignature, 'ON', new Date(), '']);
  return _json({status:'ok', watchId:watchId, enabled:true});
}
case 'getSearchWatches': {
  const watchAuth = _authorizeWebMember_(payload.token, payload.customerId, payload.deviceId, payload.app);
  if (watchAuth) return _json(watchAuth);
  const watchSheet = _getSearchWatchesSheet_();
  const watchRows = watchSheet.getDataRange().getValues();
  const watchUid = String(payload.customerId || '').trim();
  const watches = [];
  for (let wi = 1; wi < watchRows.length; wi++) {
    if (String(watchRows[wi][0]) !== watchUid) continue;
    let filters = {};
    try { filters = JSON.parse(String(watchRows[wi][4] || '{}')); } catch (e) {}
    watches.push({watchId:String(watchRows[wi][2]), label:String(watchRows[wi][3]), filters:filters, enabled:String(watchRows[wi][5]).toUpperCase() === 'ON'});
  }
  return _json({status:'ok', watches:watches});
}
case 'deleteSearchWatch': {
  const watchAuth = _authorizeWebMember_(payload.token, payload.customerId, payload.deviceId, payload.app);
  if (watchAuth) return _json(watchAuth);
  const watchSheet = _getSearchWatchesSheet_();
  const watchRows = watchSheet.getDataRange().getValues();
  const watchUid = String(payload.customerId || '').trim();
  const watchId = String(payload.watchId || '').trim();
  for (let wi = 1; wi < watchRows.length; wi++) {
    if (String(watchRows[wi][0]) === watchUid && String(watchRows[wi][2]) === watchId) {
      watchSheet.getRange(wi + 1, 6).setValue('OFF');
      return _json({status:'ok', enabled:false});
    }
  }
  return _json({status:'error', msg:'watch_not_found'});
}
case 'getMyRequestsWeb': {
  const webAuthError = _authorizeWebMember_(payload.token, payload.customerId, payload.deviceId, payload.app);
  if (webAuthError) return _json(webAuthError);
  const ss = SpreadsheetApp.openById(SS_ID);
  const sheet = ss.getSheetByName('Requests');
  if (!sheet) return _json({status:'ok', requests:[]});
  const rows = sheet.getDataRange().getValues();
  const uid = String(payload.customerId || '');
  const depositByReq = {};
  const depSheet = ss.getSheetByName('Deposits');
  if (depSheet) {
    const depRows = depSheet.getDataRange().getValues();
    if (depRows.length > 1) {
      const depHeaders = depRows[0].map(String);
      const depReqIdx = depHeaders.indexOf('ReqId');
      const depStatIdx = depHeaders.indexOf('Status');
      const depResultIdx = depHeaders.indexOf('AuctionResult');
      const depPriceIdx = depHeaders.indexOf('CarPrice');
      if (depReqIdx >= 0) {
        for (let di = 1; di < depRows.length; di++) {
          const depReqId = String(depRows[di][depReqIdx] || '');
          if (!depReqId) continue;
          depositByReq[depReqId] = {
            depositStatus: depStatIdx >= 0 ? String(depRows[di][depStatIdx] || '') : '',
            auctionResult: depResultIdx >= 0 ? String(depRows[di][depResultIdx] || '') : '',
            carPrice: depPriceIdx >= 0 ? String(depRows[di][depPriceIdx] || '') : ''
          };
        }
      }
    }
  }
  const results = [];
  for (let i = 1; i < rows.length; i++) {
    if (String(rows[i][1]) === uid) {
      const reqId = String(rows[i][0]);
      const deposit = depositByReq[reqId] || {};
      results.push({
        reqId: reqId,
        carType: String(rows[i][3]),
        budget: String(rows[i][4]),
        year: String(rows[i][5]),
        grade: String(rows[i][6]),
        condition: String(rows[i][7]),
        timeline: String(rows[i][8]),
        status: String(rows[i][9]),
        brokerId: String(rows[i][10]),
        createdAt: String(rows[i][11] || ''),
        depositStatus: deposit.depositStatus || '',
        auctionResult: deposit.auctionResult || '',
        carPrice: deposit.carPrice || ''
      });
    }
  }
  return _json({status:'ok', requests: results.reverse()});
}
case 'getMyRequests': {
  var getMyRequestsAuth = _authorizeFinanceReport_(data.serverKey);
  if (getMyRequestsAuth) return _json(getMyRequestsAuth);
  const ss = SpreadsheetApp.openById(SS_ID);
  const sheet = ss.getSheetByName('Requests');
  if (!sheet) return _json({status:'ok', requests:[]});
  const rows = sheet.getDataRange().getValues();
  const uid = String(payload.customerId || '');
  const results = [];
  for (let i = 1; i < rows.length; i++) {
    if (String(rows[i][1]) === uid) {
      results.push({
        reqId:    String(rows[i][0]),
        carType:  String(rows[i][3]),
        budget:   String(rows[i][4]),
        status:   String(rows[i][9]),
        brokerId: String(rows[i][10]),
      });
    }
  }
  return _json({status:'ok', requests: results.reverse()});
}
   // ── liftExpiredBans ──────────────────────────────────
    case "liftExpiredBans": {
      var acSheet  = ss.getSheetByName("AuctionCancels");
       if  (!acSheet) return _json({ lifted: [] });

      var rows     = acSheet.getDataRange().getValues();
      var today    = new Date();
      today.setHours(0, 0, 0, 0);
      var lifted   = [];

      for (var i = 1; i < rows.length; i++) {
        var banStatus = String(rows[i][5] || "").trim();
        var banExpire = String(rows[i][6] || "").trim();

        if (!banStatus || banStatus === "LIFETIME_BAN" || banStatus === "LIFTED") continue;
        if (banStatus !== "BAN_7D" && banStatus !== "BAN_1M") continue;
        if (!banExpire || banExpire === "LIFETIME") continue;

        var parts = banExpire.split("/");
        if (parts.length !== 3) continue;
        var expireDate = new Date(
          parseInt(parts[2]),
          parseInt(parts[1]) - 1,
          parseInt(parts[0])
        );
        expireDate.setHours(0, 0, 0, 0);

        if (today > expireDate) {
          acSheet.getRange(i + 1, 6).setValue("LIFTED");
          acSheet.getRange(i + 1, 7).setValue("");
          lifted.push({
            customerId: String(rows[i][0]),
            username:   String(rows[i][1] || ""),
            banStatus:  banStatus,
          });
        }
      }
      return _json({ lifted: lifted });
    }
     case 'getPaymentQR': {
      const method = data.method || '';
      if (!method) {
        return _json({ ok: false, error: 'method required' });
      }
      const result = getPaymentQR_(method);
      if (!result || !result.fileId) {
        return _json({ ok: false, error: 'QR not configured for ' + method });
      }
      return _json({
        ok: true,
        method: result.method,
        fileId: result.fileId,
        updated: result.updated
      });
    }
    
    case 'setPaymentQR': {
      var setPaymentQRAuth = _authorizeFinanceReport_(data.serverKey);
      if (setPaymentQRAuth) return _json(setPaymentQRAuth);
      const method = data.method || '';
      const fileId = data.fileId || '';
      const adminName = data.adminName || 'admin';
      if (!method || !fileId) {
        return _json({ ok: false, error: 'method and fileId required' });
      }
      const result = setPaymentQR_(method, fileId, adminName);
      return _json(result);
    }
      // ── Places directory (admin-added, member-visible) ────
      case "addPlace": {
        var addPlaceAuth = _authorizeFinanceReport_(data.serverKey);
        if (addPlaceAuth) return _json(addPlaceAuth);
        return _json(addPlace(data.place || data));
      }
      case "removePlace": {
        var removePlaceAuth = _authorizeFinanceReport_(data.serverKey);
        if (removePlaceAuth) return _json(removePlaceAuth);
        return _json(removePlace(data.placeId));
      }
      case "getPlaces":
        // Public read: this is a plain business directory (name/location/
        // phone), not sensitive member data, and the website's Locations
        // tab needs it reachable without an admin server key.
        return _json({status:"ok", places: getPlaces()});

      // ── Price Data (POST) ─────────────────────────────────
      default:
        var defaultAddCarAuth = _authorizeFinanceReport_(data.serverKey);
        if (defaultAddCarAuth) return _json(defaultAddCarAuth);
        var sheet = ss.getSheetByName("Sheet1");
        sheet.appendRow([
          data.date, data.chassis, data.model, data.color,
          data.year, data.price, data.location, data.added_by,
          data.image_url || ""
        ]);
        return _json({status:"ok"});
    }

  } catch(err) {
    return ContentService
      .createTextOutput(JSON.stringify({status:"error", message:err.toString()}))
      .setMimeType(ContentService.MimeType.JSON);
  } finally {
    if (lockHeld) lock.releaseLock();
  }
  
}
     // ── Audit Log ──────────────────────────────────────────
function writeAuditLog(actor, action, target, result) {
  try {
    var ss  = SpreadsheetApp.openById(SS_ID);
    var log = ss.getSheetByName('AuditLog');
    if (!log) {
      log = ss.insertSheet('AuditLog');
      log.appendRow(['Timestamp','Actor','Action','Target','Result']);
      log.getRange(1,1,1,5).setFontWeight('bold')
        .setBackground('#1A2535').setFontColor('#FFFFFF');
    }
    var now = Utilities.formatDate(new Date(),'Asia/Bangkok','dd/MM/yyyy HH:mm:ss');
    log.appendRow([now, actor, action, target, result]);
  } catch(e) {}
}
function _normalizeWatchFilters_(filters) {
  var allowed = ['model','color','year','loc','priceMin','priceMax','sort'];
  var result = {};
  allowed.forEach(function(key) {
    var value = String(filters && filters[key] || '').trim();
    if (value) result[key] = value.slice(0, 80);
  });
  return result;
}
function _getSearchWatchesSheet_() {
  var ss = SpreadsheetApp.openById(SS_ID);
  var sheet = ss.getSheetByName('SearchWatches');
  if (!sheet) {
    sheet = ss.insertSheet('SearchWatches');
    sheet.appendRow(['UserID','Username','WatchID','Label','FiltersJson','Enabled','CreatedAt','LastNotifiedKeys']);
    sheet.getRange(1, 1, 1, 8).setFontWeight('bold');
  }
  return sheet;
}
function _watchCarMatches_(car, filters) {
  var model = String(car.model || '').toUpperCase();
  var color = String(car.color || '').toUpperCase();
  var loc = String(car.location || '').toUpperCase();
  var wantedModel = String(filters.model || '').toUpperCase();
  var wantedColor = String(filters.color || '').toUpperCase();
  var wantedLoc = String(filters.loc || '').toUpperCase();
  var year = Number(car.year || 0);
  var price = Number(String(car.price || '').replace(/[^0-9.]/g, '')) || 0;
  if (wantedModel && model.indexOf(wantedModel) === -1) return false;
  if (wantedColor && color.indexOf(wantedColor) === -1) return false;
  if (wantedLoc && loc.indexOf(wantedLoc) === -1) return false;
  if (filters.year && String(year) !== String(filters.year)) return false;
  if (filters.priceMin && price < Number(filters.priceMin)) return false;
  if (filters.priceMax && price > Number(filters.priceMax)) return false;
  return true;
}
function _sendSearchWatchTelegram_(chatId, text) {
  var botToken = PropertiesService.getScriptProperties().getProperty('BOT_TOKEN');
  if (!botToken || !chatId) return false;
  try {
    UrlFetchApp.fetch('https://api.telegram.org/bot' + botToken + '/sendMessage', {method:'post', contentType:'application/json', payload:JSON.stringify({chat_id:String(chatId), text:text})});
    return true;
  } catch (e) {
    Logger.log('Search watch Telegram send failed: ' + e);
    return false;
  }
}
function checkSearchWatches() {
  var ss = SpreadsheetApp.openById(SS_ID);
  var watchSheet = _getSearchWatchesSheet_();
  var carSheet = ss.getSheetByName('Sheet1');
  if (!carSheet || carSheet.getLastRow() < 2) return {status:'ok', notified:0};
  var carRows = carSheet.getDataRange().getValues();
  var watches = watchSheet.getDataRange().getValues();
  var notified = 0;
  for (var wi = 1; wi < watches.length; wi++) {
    if (String(watches[wi][5]).toUpperCase() !== 'ON') continue;
    var filters = {}; try { filters = JSON.parse(String(watches[wi][4] || '{}')); } catch (e) {}
    var previous = String(watches[wi][7] || '').split('|').filter(Boolean);
    var fresh = [];
    for (var ci = 1; ci < carRows.length && fresh.length < 3; ci++) {
      var row = carRows[ci];
      var car = {date:row[0], chassis:row[1], model:row[2], color:row[3], year:row[4], price:row[5], location:row[6]};
      if (!_watchCarMatches_(car, filters)) continue;
      var key = String(car.date || '') + ':' + String(car.chassis || '') + ':' + String(car.price || '');
      if (previous.indexOf(key) === -1) fresh.push({key:key, car:car});
    }
    if (!fresh.length) continue;
    var lines = fresh.map(function(item) { var car=item.car; return '🚗 ' + String(car.model || '-') + ' · ' + String(car.chassis || '-') + ' · ฿' + String(car.price || '-') + ' · ' + String(car.location || '-'); });
    var text = '🔔 JACC Saved Search Alert\n\n' + String(watches[wi][3] || 'ကားရှာဖွေမှု') + '\n\n' + lines.join('\n') + '\n\nWebsite မှ detail စစ်ပြီး broker/admin နှင့် confirm လုပ်ပါ။';
    if (_sendSearchWatchTelegram_(watches[wi][0], text)) {
      var keys = previous.concat(fresh.map(function(item){return item.key;})).slice(-30);
      watchSheet.getRange(wi + 1, 8).setValue(keys.join('|'));
      notified++;
    }
  }
  return {status:'ok', notified:notified};
}
function installSearchWatchTrigger() {
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) if (triggers[i].getHandlerFunction() === 'checkSearchWatches') return {status:'ok', message:'already_installed'};
  ScriptApp.newTrigger('checkSearchWatches').timeBased().everyHours(1).create();
  return {status:'ok', message:'installed'};
}
function _normalizeRequestId_(value) {
  return String(value || "")
    .replace(/[\u0000-\u001F\u007F\u200B-\u200D\u2060\uFEFF]/g, "")
    .trim()
    .toUpperCase();
}

function _validRequestId_(value) {
  return /^[AR][A-Z0-9-]{5,64}$/.test(String(value || ""));
}

function _requestIdExists_(sheet, reqId) {
  if (!sheet || sheet.getLastRow() < 2) return false;
  var rows = sheet.getRange(2, 1, sheet.getLastRow() - 1, 1).getValues();
  var wanted = _normalizeRequestId_(reqId);
  for (var i = 0; i < rows.length; i++) {
    if (_normalizeRequestId_(rows[i][0]) === wanted) return true;
  }
  return false;
}

function _newRequestId_(sheet, prefix) {
  var safePrefix = String(prefix || "R").toUpperCase() === "A" ? "A" : "R";
  for (var attempt = 0; attempt < 20; attempt++) {
    var candidate = safePrefix + Utilities.getUuid().replace(/-/g, "").slice(0, 10).toUpperCase();
    if (!_requestIdExists_(sheet, candidate)) return candidate;
  }
  throw new Error("request_id_generation_failed");
}

function _authorizeWebMember_(token, userId, deviceId, app) {
  var safeToken = String(token || '').trim();
  var safeUserId = String(userId || '').trim();
  if (!safeToken || !safeUserId) return {status:'error', msg:'auth_required'};
  var tokenResult = verifyToken(safeToken, deviceId, app, safeUserId);
  if (tokenResult.status !== 'ok' || String(tokenResult.userId || '') !== safeUserId) {
    return {status:'error', msg:tokenResult.message || tokenResult.msg || 'invalid_session'};
  }
  return null;
}
// ── Helper: JSON response ──────────────────────────────────
function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function _parseMemberDate(value) {
  if (value instanceof Date && !isNaN(value.getTime())) {
    var dateValue = new Date(value.getTime());
    dateValue.setHours(23, 59, 59, 999);
    return dateValue;
  }

  var text = String(value || "").trim();
  var match = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  var parsed;
  if (match) {
    parsed = new Date(Number(match[3]), Number(match[2]) - 1, Number(match[1]));
  } else {
    match = text.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
    parsed = match
      ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
      : new Date(text);
  }

  if (isNaN(parsed.getTime())) return null;
  parsed.setHours(23, 59, 59, 999);
  return parsed;
}

function _addMembershipPeriod_(baseDate, days, months) {
  var result = new Date(baseDate.getTime());
  var monthCount = parseInt(months, 10) || 0;
  if (monthCount > 0) {
    var originalDay = result.getDate();
    result.setDate(1);
    result.setMonth(result.getMonth() + monthCount);
    var lastDay = new Date(result.getFullYear(), result.getMonth() + 1, 0).getDate();
    result.setDate(Math.min(originalDay, lastDay));
  } else {
    result.setDate(result.getDate() + (parseInt(days, 10) || 0));
  }
  result.setHours(23, 59, 59, 999);
  return result;
}

function _normalizePackage(value) {
  var pkg = String(value || "CH").trim().toUpperCase()
    .replace(/[_-]+/g, " ");
  if (pkg.indexOf("WEB") !== -1 || pkg.indexOf("PREMIUM") !== -1) return "WEB";
  if (pkg === "CH" || pkg === "CH PROMO" || pkg.indexOf("STANDARD") !== -1 || pkg === "CHANNEL") return "CH";
  return pkg.replace(/\s+/g, "-") || "CH";
}

// ── Finance report helpers ─────────────────────────────────
function _financeHeaders_() {
  return [
    "Date","Time","UserID","Username","Package","Months",
    "Amount(Ks)","PayType","TransactionNo","TransferTo","Sender","Status",
    "EntryType","Source","PaymentID","ApprovedBy","ExpireDate","Note"
  ];
}

function _financeHeaderKey_(value) {
  return String(value || "").trim().toUpperCase().replace(/[\s_()\-]/g, "");
}

function _ensureFinanceHeaders_(sheet) {
  var headers = _financeHeaders_();
  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  } else {
    var firstWidth = Math.max(sheet.getLastColumn(), headers.length);
    var firstRow = sheet.getRange(1, 1, 1, firstWidth).getValues()[0];
    var firstKey = _financeHeaderKey_(firstRow[0]);
    var amountKey = _financeHeaderKey_(firstRow[6]);
    if (firstKey !== "DATE" || amountKey.indexOf("AMOUNT") === -1) {
      sheet.insertRowBefore(1);
    }
    var currentWidth = Math.max(sheet.getLastColumn(), headers.length);
    var current = sheet.getRange(1, 1, 1, currentWidth).getValues()[0];
    for (var hi = 0; hi < headers.length; hi++) {
      if (!String(current[hi] || "").trim()) {
        sheet.getRange(1, hi + 1).setValue(headers[hi]);
      }
    }
  }
  sheet.getRange(1, 1, 1, headers.length).setFontWeight("bold")
    .setBackground("#1A2535").setFontColor("#FFFFFF");
}

function _financeColumns_(headers) {
  var map = {};
  for (var ci = 0; ci < headers.length; ci++) {
    var key = _financeHeaderKey_(headers[ci]);
    if (key && map[key] === undefined) map[key] = ci;
  }
  return map;
}

function _financeColumn_(map, names, fallback) {
  for (var ni = 0; ni < names.length; ni++) {
    var idx = map[_financeHeaderKey_(names[ni])];
    if (idx !== undefined) return idx;
  }
  return fallback;
}

function _financeDateKey_(value) {
  if (value instanceof Date && !isNaN(value.getTime())) {
    return Utilities.formatDate(value, "Asia/Bangkok", "yyyy-MM-dd");
  }
  var text = String(value || "").trim();
  var match = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (match) return match[3] + "-" + ("0" + match[2]).slice(-2) + "-" + ("0" + match[1]).slice(-2);
  match = text.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (match) return match[1] + "-" + ("0" + match[2]).slice(-2) + "-" + ("0" + match[3]).slice(-2);
  return "";
}

function _financeAmount_(value) {
  var text = String(value === null || value === undefined ? "" : value)
    .trim().replace(/,/g, "").replace(/ks/ig, "").trim();
  if (!text || text.toUpperCase() === "UNKNOWN") return null;
  var amount = Number(text);
  return isFinite(amount) && amount >= 0 ? amount : null;
}

function _financeMethod_(value) {
  var text = String(value || "").trim().toUpperCase();
  if (text.indexOf("KPAY") !== -1 || text.indexOf("KBZPAY") !== -1 || text.indexOf("KBZ BANK") !== -1) return "KPay";
  if (text.indexOf("WAVE") !== -1) return "Wave";
  if (text.indexOf("BANK") !== -1 || text === "CB" || text.indexOf("CB PAY") !== -1) return "Bank";
  if (text === "MANUAL") return "Manual";
  if (text === "PROMO") return "Promo";
  return text ? "Other" : "Other";
}

function _financeEntryType_(entryType, source) {
  var text = String(entryType || "").trim().toUpperCase();
  var src = String(source || "").trim().toUpperCase();
  if (text.indexOf("UPGRADE") !== -1) return "UPGRADE";
  if (text.indexOf("RENEW") !== -1) return "RENEW";
  if (text.indexOf("NEW") !== -1 || text.indexOf("ADD") !== -1) return "NEW";
  if (text.indexOf("MANUAL") !== -1 || src.indexOf("MANUAL") !== -1) return "MANUAL";
  if (text.indexOf("PROMO") !== -1 || src.indexOf("PROMO") !== -1) return "PROMO";
  return "UNKNOWN";
}

function _authorizeFinanceReport_(serverKey) {
  // The Railway env var this value is copied from is named SHEET_SERVER_KEY,
  // which has twice led to the Script Property being saved under that same
  // name instead of JACC_SERVER_KEY (the name this code actually reads) —
  // each time silently breaking every gated action with server_key_not_configured
  // until someone notices. Accept either property name so a mismatched name
  // no longer breaks production; JACC_SERVER_KEY still wins if both are set.
  var props = PropertiesService.getScriptProperties();
  var expected = String(props.getProperty("JACC_SERVER_KEY") || props.getProperty("SHEET_SERVER_KEY") || "").trim();
  if (!expected) return {status:"error", message:"server_key_not_configured"};
  if (!serverKey || String(serverKey).trim() !== expected) return {status:"error", message:"unauthorized"};
  return null;
}

function getFinanceReport_(month) {
  var monthText = String(month || "").trim();
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(monthText)) {
    return {status:"error", message:"invalid_month"};
  }
  var finSheet = SpreadsheetApp.openById(SS_ID).getSheetByName(FINANCE_SHEET);
  var summary = {
    month: monthText,
    recordCount: 0,
    paymentCount: 0,
    activityCount: 0,
    totalAmount: 0,
    knownAmountCount: 0,
    unknownAmountCount: 0,
    duplicateCount: 0,
    missingTransactionCount: 0,
    byMethod: {
      KPay:{count:0,total:0}, Wave:{count:0,total:0},
      Bank:{count:0,total:0}, Other:{count:0,total:0}
    },
    byEntryType: {NEW:0, RENEW:0, UPGRADE:0, MANUAL:0, PROMO:0, UNKNOWN:0},
    bySource: {PAYMENT_SLIP:0, MANUAL:0, PROMO:0, OTHER:0},
    reviewItems: [],
    legacyUnclassifiedCount: 0,
    legacyKnownAmountCount: 0,
    legacyAmount: 0
  };
  if (!finSheet || finSheet.getLastRow() < 1) return {status:"ok", summary:summary};

  _ensureFinanceHeaders_(finSheet);
  var rows = finSheet.getDataRange().getValues();
  if (rows.length < 2) return {status:"ok", summary:summary};
  var columns = _financeColumns_(rows[0]);
  var dateCol = _financeColumn_(columns, ["Date"], 0);
  var userCol = _financeColumn_(columns, ["UserID", "TelegramID"], 2);
  var usernameCol = _financeColumn_(columns, ["Username"], 3);
  var packageCol = _financeColumn_(columns, ["Package"], 4);
  var amountCol = _financeColumn_(columns, ["Amount(Ks)", "Amount"], 6);
  var payTypeCol = _financeColumn_(columns, ["PayType", "Method"], 7);
  var txCol = _financeColumn_(columns, ["TransactionNo", "Transaction No"], 8);
  var statusCol = _financeColumn_(columns, ["Status"], 11);
  var entryCol = _financeColumn_(columns, ["EntryType", "Action", "MembershipType"], 12);
  var sourceCol = _financeColumn_(columns, ["Source"], 13);

  var seenTransactions = {};
  for (var ri = 1; ri < rows.length; ri++) {
    var row = rows[ri];
    var dateKey = _financeDateKey_(row[dateCol]);
    if (!dateKey || dateKey.slice(0, 7) !== monthText) continue;
    var status = String(row[statusCol] || "").trim().toUpperCase();
    var rawSource = String(row[sourceCol] || "").trim().toUpperCase();
    var rawEntryType = String(row[entryCol] || "").trim();
    var tx = String(row[txCol] || "").trim();
    var amount = _financeAmount_(row[amountCol]);
    var method = _financeMethod_(row[payTypeCol]);
    var reviewReason = "";

    // Legacy rows created before the audit metadata existed must not be
    // presented as verified current revenue. Keep them visible for review.
    if (!rawSource && !rawEntryType) {
      summary.legacyUnclassifiedCount++;
      if (amount === null) {
        summary.unknownAmountCount++;
      } else {
        summary.legacyKnownAmountCount++;
        summary.legacyAmount += amount;
      }
      if (summary.reviewItems.length < 25) {
        summary.reviewItems.push({
          row:ri + 1, date:dateKey,
          userId:String(row[userCol] || ""),
          username:String(row[usernameCol] || ""),
          package:String(row[packageCol] || ""),
          amount:amount === null ? "" : amount,
          method:method, entryType:"UNKNOWN",
          reason:"legacy_unclassified"
        });
      }
      continue;
    }

    var source = rawSource;
    if (!source && status === "APPROVED") source = "PAYMENT_SLIP";
    var entryType = _financeEntryType_(rawEntryType, source);
    var isActivity = status === "APPROVED" || status === "NO_PAYMENT" || status === "PROMO" || source === "MANUAL" || source === "PROMO";
    if (!isActivity) {
      summary.reviewItems.push({row:ri + 1, date:dateKey, userId:String(row[userCol] || ""), reason:"status:" + (status || "missing")});
      continue;
    }
    if (tx && seenTransactions[tx]) {
      summary.duplicateCount++;
      summary.reviewItems.push({row:ri + 1, date:dateKey, userId:String(row[userCol] || ""), reason:"duplicate_transaction"});
      continue;
    }
    if (tx) seenTransactions[tx] = true;
    if (!tx && method !== "Manual" && method !== "Promo") {
      summary.missingTransactionCount++;
      reviewReason = "missing_transaction";
    }

    summary.recordCount++;
    summary.activityCount++;
    summary.byEntryType[entryType] = (summary.byEntryType[entryType] || 0) + 1;
    var sourceBucket = source === "PAYMENT_SLIP" ? "PAYMENT_SLIP" : (source === "MANUAL" ? "MANUAL" : (source === "PROMO" ? "PROMO" : "OTHER"));
    summary.bySource[sourceBucket] = (summary.bySource[sourceBucket] || 0) + 1;
    var isRevenue = status === "APPROVED" && method !== "Manual" && method !== "Promo" && source !== "MANUAL" && source !== "PROMO";
    if (isRevenue) {
      summary.paymentCount++;
      if (amount === null) {
        summary.unknownAmountCount++;
        reviewReason = reviewReason || "missing_amount";
      } else {
        summary.knownAmountCount++;
        summary.totalAmount += amount;
        if (!summary.byMethod[method]) method = "Other";
        summary.byMethod[method].count++;
        summary.byMethod[method].total += amount;
      }
    }
    if (entryType === "UNKNOWN") reviewReason = reviewReason || "missing_entry_type";
    if (reviewReason && summary.reviewItems.length < 25) {
      summary.reviewItems.push({
        row:ri + 1, date:dateKey, userId:String(row[userCol] || ""),
        username:String(row[usernameCol] || ""), package:String(row[packageCol] || ""),
        amount:amount === null ? "" : amount, method:method, entryType:entryType,
        reason:reviewReason
      });
    }
  }
  return {status:"ok", summary:summary};
}

// ── Server-side payment transaction helpers ─────────────────
function _transactionIdTokens_(value) {
  return String(value || "").split(/[|,]/).map(function(token) {
    return String(token || "").trim();
  }).filter(function(token) {
    return token && token.toUpperCase() !== "UNKNOWN";
  });
}

function _transactionStateKey_(paymentId) {
  var safe = String(paymentId || "").replace(/[^A-Za-z0-9_.-]/g, "_");
  return "JACC_TXN_STATE_" + safe.slice(0, 180);
}

function _memberDateText_(value) {
  var parsed = _parseMemberDate(value);
  return parsed
    ? Utilities.formatDate(parsed, "Asia/Bangkok", "dd/MM/yyyy")
    : String(value || "").trim();
}

function _memberRecordFromRow_(values, rowNumber) {
  return {
    row: rowNumber,
    userId: String(values[C_USERID] || ""),
    username: String(values[C_USERNAME] || ""),
    startDate: _memberDateText_(values[C_START]),
    expireDate: _memberDateText_(values[C_EXPIRE]),
    status: String(values[C_STATUS] || "").trim().toUpperCase(),
    package: _normalizePackage(values[C_PACKAGE]),
    password: String(values[C_PASSWORD] || "").trim()
  };
}

function _findMemberRecord_(sheet, userId) {
  var rows = sheet.getDataRange().getValues();
  var matches = [];
  for (var i = 1; i < rows.length; i++) {
    if (String(rows[i][C_USERID] || "").trim() === String(userId || "").trim()) {
      matches.push(_memberRecordFromRow_(rows[i], i + 1));
    }
  }
  return {
    count: matches.length,
    record: matches.length === 1 ? matches[0] : null
  };
}

function _financeDuplicatePayment_(sheet, tokens) {
  if (!tokens || !tokens.length || sheet.getLastRow() < 2) return null;
  var rows = sheet.getDataRange().getValues();
  for (var i = 1; i < rows.length; i++) {
    var existing = _transactionIdTokens_(String(rows[i][8] || "") + "|" + String(rows[i][14] || ""));
    for (var ti = 0; ti < tokens.length; ti++) {
      if (existing.indexOf(tokens[ti]) !== -1) {
        return {
          row: i + 1,
          userId: String(rows[i][2] || ""),
          transactionNo: String(rows[i][8] || ""),
          paymentId: String(rows[i][14] || ""),
          status: String(rows[i][11] || "")
        };
      }
    }
  }
  return null;
}

function _setFinanceTransactionState_(sheet, rowNumber, status, entryType, source,
                                      paymentId, approvedBy, expireDate, note) {
  sheet.getRange(rowNumber, 12, 1, 7).setValues([[
    status || "", entryType || "", source || "", paymentId || "",
    approvedBy || "", expireDate || "", note || ""
  ]]);
}

function _pendingTransactionMeta_(note) {
  var meta = {};
  String(note || "").split(";").forEach(function(part) {
    var bits = part.split("=");
    if (bits.length < 2) return;
    var key = String(bits.shift() || "").trim();
    if (key) meta[key] = bits.join("=").trim();
  });
  return meta;
}

function _pendingMemberMatches_(member, meta) {
  if (!member || member.status !== "ACTIVE") return false;
  var targetPackage = _normalizePackage(meta.package || "");
  if (!targetPackage || member.package !== targetPackage) return false;
  var days = parseInt(meta.days || "", 10);
  if (!isFinite(days) || days <= 0) return false;
  var currentExpire = _parseMemberDate(member.expireDate);
  if (!currentExpire) return false;

  var baseDate = null;
  if (String(meta.previousStatus || "").toUpperCase() === "ACTIVE") {
    baseDate = _parseMemberDate(meta.previousExpire || "");
  }
  if (!baseDate) {
    baseDate = _parseMemberDate(meta.financeDate || "");
  }
  if (!baseDate) {
    baseDate = _parseMemberDate(Utilities.formatDate(new Date(), "Asia/Bangkok", "dd/MM/yyyy"));
  }
  if (!baseDate) return false;

  var expectedExpire = _addMembershipPeriod_(baseDate, days, meta.months);
  // Recover only the exact member mutation represented by this pending row.
  // If another renewal ran afterward, require manual review instead of
  // attributing that later expiry to this transaction.
  if (currentExpire.getTime() !== expectedExpire.getTime()) return false;
  if (targetPackage === "WEB" && !String(member.password || "").trim()) return false;
  return true;
}

function _recoverPendingTransaction_(financeSheet, membersSheet, duplicate, payment, stateStore) {
  if (!duplicate || String(duplicate.status || "").trim().toUpperCase() !== "PENDING") return null;
  var rows = financeSheet.getDataRange().getValues();
  var row = rows[duplicate.row - 1] || [];
  var meta = _pendingTransactionMeta_(row[17]);
  var userId = String(payment.userId || "").trim();
  if (!userId || String(meta.userId || "").trim() !== userId) return null;
  var memberLookup = _findMemberRecord_(membersSheet, userId);
  if (memberLookup.count !== 1 || !_pendingMemberMatches_(memberLookup.record, meta)) return null;

  var member = memberLookup.record;
  var paymentId = String(payment.paymentId || payment.transactionNo || duplicate.paymentId || duplicate.transactionNo || "").trim();
  var entryType = String(meta.entryType || "").trim() || "RENEW";
  var source = String(meta.source || "PAYMENT_SLIP").trim() || "PAYMENT_SLIP";
  var approvedBy = String(payment.approvedBy || meta.approvedBy || "").trim();
  var note = "Recovered after lost response; canonical member matched; transaction committed";
  _setFinanceTransactionState_(financeSheet, duplicate.row, "APPROVED", entryType, source,
    paymentId, approvedBy, member.expireDate, note);
  writeAuditLog(approvedBy || "Admin", "PAYMENT_TRANSACTION", userId,
    "RECOVERED:" + entryType + ":" + paymentId);
  var stateKey = _transactionStateKey_(paymentId || duplicate.paymentId || duplicate.transactionNo);
  if (stateKey) stateStore.deleteProperty(stateKey);
  return {
    status:"ok", result:"recovered", duplicate:true, entryType:entryType,
    package:member.package, member:member, financeRow:duplicate.row,
    password:member.password
  };
}

function inspectPaymentTransaction_(payment) {
  payment = payment || {};
  var userId = String(payment.userId || "").trim();
  var paymentId = String(payment.paymentId || payment.transactionNo || "").trim();
  var tokens = _transactionIdTokens_(paymentId);
  if (!tokens.length) return {status:"error", message:"transaction_no_required"};

  var ss = SpreadsheetApp.openById(SS_ID);
  var membersSheet = ss.getSheetByName(MEMBERS);
  if (!membersSheet) return {status:"error", message:"members_sheet_missing"};
  var financeSheet = ss.getSheetByName(FINANCE_SHEET);
  if (!financeSheet) {
    return {
      status:"ok", found:false, state:"", member:_findMemberRecord_(membersSheet, userId).record || null
    };
  }
  _ensureFinanceHeaders_(financeSheet);

  var stateStore = PropertiesService.getScriptProperties();
  var stateKey = _transactionStateKey_(paymentId);
  var state = String(stateStore.getProperty(stateKey) || "").trim();
  var duplicate = _financeDuplicatePayment_(financeSheet, tokens);
  var memberLookup = _findMemberRecord_(membersSheet, userId);
  if (!duplicate) {
    return {
      status:"ok", found:false, state:state,
      member:memberLookup.record || null, memberCount:memberLookup.count
    };
  }
  if (userId && String(duplicate.userId || "").trim() !== userId) {
    return {status:"error", message:"transaction_already_used", financeRow:duplicate.row};
  }

  var rows = financeSheet.getDataRange().getValues();
  var row = rows[duplicate.row - 1] || [];
  return {
    status:"ok", found:true, state:state, financeRow:duplicate.row,
    finance: {
      date:String(row[0] || ""), time:String(row[1] || ""),
      userId:String(row[2] || ""), username:String(row[3] || ""),
      package:String(row[4] || ""), months:String(row[5] || ""),
      amount:String(row[6] || ""), payType:String(row[7] || ""),
      transactionNo:String(row[8] || ""), status:String(row[11] || "").trim().toUpperCase(),
      entryType:String(row[12] || ""), source:String(row[13] || ""),
      paymentId:String(row[14] || ""), approvedBy:String(row[15] || ""),
      expireDate:String(row[16] || ""), note:String(row[17] || "")
    },
    member:memberLookup.record || null, memberCount:memberLookup.count
  };
}

var PAYMENT_DRAFT_SHEET = "Payment_Drafts";
var PAYMENT_DRAFT_HEADERS = [
  "DraftKey", "UserID", "Username", "Package", "Months", "Amount",
  "Method", "TotalPaid", "SlipsJson", "SlipInfoJson", "Status",
  "CreatedAt", "UpdatedAt", "LastTransactionNo"
];

function _getPaymentDraftSheet_() {
  var ss = SpreadsheetApp.openById(SS_ID);
  var sheet = ss.getSheetByName(PAYMENT_DRAFT_SHEET);
  if (!sheet) {
    sheet = ss.insertSheet(PAYMENT_DRAFT_SHEET);
    sheet.appendRow(PAYMENT_DRAFT_HEADERS);
  } else if (sheet.getLastRow() < 1) {
    sheet.appendRow(PAYMENT_DRAFT_HEADERS);
  }
  return sheet;
}

function _paymentDraftSafeSlips_(slips) {
  return (Array.isArray(slips) ? slips : []).map(function(item) {
    var info = item && item.slip_info ? item.slip_info : {};
    return {
      slip_info: {
        AMOUNT: String(info.AMOUNT || ""),
        DATE: String(info.DATE || ""),
        TIME: String(info.TIME || ""),
        TYPE: String(info.TYPE || ""),
        TRANSACTION_NO: String(info.TRANSACTION_NO || info.REFERENCE || ""),
        REFERENCE: String(info.REFERENCE || ""),
        SENDER: String(info.SENDER || ""),
        TRANSFER_TO: String(info.TRANSFER_TO || ""),
        RECEIVER: String(info.RECEIVER || "")
      },
      amount_num: Number(item && item.amount_num || 0),
      txn_key: String(item && item.txn_key || "")
    };
  });
}

function _savePaymentDraft_(draft) {
  draft = draft || {};
  var userId = String(draft.userId || "").trim();
  if (!userId) return {status:"error", message:"user_id_required"};
  var sheet = _getPaymentDraftSheet_();
  var now = Utilities.formatDate(new Date(), "Asia/Bangkok", "dd/MM/yyyy HH:mm:ss");
  var slips = _paymentDraftSafeSlips_(draft.slips || []);
  var rows = sheet.getDataRange().getValues();
  var rowNumber = 0;
  var createdAt = now;
  for (var i = rows.length - 1; i >= 1; i--) {
    if (String(rows[i][1] || "").trim() !== userId) continue;
    if (String(rows[i][10] || "").trim().toUpperCase() === "CLEARED") break;
    rowNumber = i + 1;
    createdAt = String(rows[i][11] || now);
    break;
  }
  var values = [
    "USER-" + userId, userId, String(draft.username || ""),
    String(draft.package || "CH").trim().toUpperCase(),
    parseInt(draft.months, 10) || 1, _financeAmount_(draft.amount) || 0,
    String(draft.method || "").trim(), Number(draft.total_paid || 0),
    JSON.stringify(slips), JSON.stringify(draft.slip_info || {}),
    "READY", createdAt, now,
    String((slips.length && slips[slips.length - 1].slip_info.TRANSACTION_NO) || "")
  ];
  if (rowNumber) sheet.getRange(rowNumber, 1, 1, values.length).setValues([values]);
  else sheet.appendRow(values);
  return {status:"ok", result:"saved", draftKey:"USER-" + userId};
}

function _getPaymentDraft_(draft) {
  draft = draft || {};
  var userId = String(draft.userId || "").trim();
  if (!userId) return {status:"error", message:"user_id_required"};
  var sheet = _getPaymentDraftSheet_();
  var rows = sheet.getDataRange().getValues();
  for (var i = rows.length - 1; i >= 1; i--) {
    if (String(rows[i][1] || "").trim() !== userId) continue;
    if (String(rows[i][10] || "").trim().toUpperCase() === "CLEARED") continue;
    var slips = [];
    var slipInfo = {};
    try { slips = JSON.parse(String(rows[i][8] || "[]")); } catch (e) {}
    try { slipInfo = JSON.parse(String(rows[i][9] || "{}")); } catch (e) {}
    return {
      status:"ok", found:true,
      draft: {
        userId:String(rows[i][1] || ""), username:String(rows[i][2] || ""),
        package:String(rows[i][3] || "CH"), months:parseInt(rows[i][4], 10) || 1,
        amount:Number(rows[i][5] || 0), method:String(rows[i][6] || ""),
        total_paid:Number(rows[i][7] || 0), slips:slips, slip_info:slipInfo,
        status:String(rows[i][10] || "READY")
      }
    };
  }
  return {status:"ok", found:false};
}

function _clearPaymentDraft_(draft) {
  draft = draft || {};
  var userId = String(draft.userId || "").trim();
  if (!userId) return {status:"error", message:"user_id_required"};
  var sheet = _getPaymentDraftSheet_();
  var rows = sheet.getDataRange().getValues();
  for (var i = rows.length - 1; i >= 1; i--) {
    if (String(rows[i][1] || "").trim() !== userId) continue;
    if (String(rows[i][10] || "").trim().toUpperCase() === "CLEARED") continue;
    sheet.getRange(i + 1, 11).setValue("CLEARED");
    sheet.getRange(i + 1, 13).setValue(Utilities.formatDate(new Date(), "Asia/Bangkok", "dd/MM/yyyy HH:mm:ss"));
    sheet.getRange(i + 1, 14).setValue(String(draft.transactionNo || ""));
    return {status:"ok", result:"cleared"};
  }
  return {status:"ok", result:"not_found"};
}

function approvePaymentTransaction_(payment) {
  payment = payment || {};
  var userId = String(payment.userId || "").trim();
  var username = String(payment.username || "").trim();
  var targetPackage = _normalizePackage(payment.package || "CH");
  var source = String(payment.source || "PAYMENT_SLIP").trim().toUpperCase();
  var approvedBy = String(payment.approvedBy || "").trim();
  var expectedAmount = _financeAmount_(payment.expectedAmount);
  var receivedAmount = _financeAmount_(payment.receivedAmount);
  var calendarMonths = parseInt(payment.months, 10) || 0;
  var days = parseInt(payment.days || (calendarMonths * 30), 10);
  var method = _financeMethod_(payment.payType || payment.method || "");
  var transactionNo = String(payment.transactionNo || payment.paymentId || "").trim();
  var paymentId = String(payment.paymentId || transactionNo).trim();
  var tokens = _transactionIdTokens_(paymentId || transactionNo);
  var dateText = String(payment.date || "").trim();

  if (!userId) return {status:"error", message:"user_id_required"};
  if (targetPackage !== "CH" && targetPackage !== "WEB") {
    return {status:"error", message:"invalid_package"};
  }
  if (source !== "PAYMENT_SLIP") {
    return {status:"error", message:"payment_source_not_supported"};
  }
  if (!approvedBy) return {status:"error", message:"approved_by_required"};
  if (!isFinite(days) || days <= 0) return {status:"error", message:"invalid_expire_days"};
  if (method !== "KPay" && method !== "Wave" && method !== "Bank") {
    return {status:"error", message:"invalid_payment_method"};
  }
  if (expectedAmount === null || expectedAmount <= 0 || receivedAmount === null || receivedAmount <= 0) {
    return {status:"error", message:"payment_amount_required"};
  }
  if (expectedAmount !== receivedAmount) {
    return {status:"error", message:"payment_amount_mismatch", expectedAmount:expectedAmount, receivedAmount:receivedAmount};
  }
  if (!tokens.length || tokens.some(function(token) { return token.length < 5; })) {
    return {status:"error", message:"transaction_no_required"};
  }
  if (!_financeDateKey_(dateText)) return {status:"error", message:"payment_date_invalid"};

  var ss = SpreadsheetApp.openById(SS_ID);
  var membersSheet = ss.getSheetByName(MEMBERS);
  if (!membersSheet) return {status:"error", message:"members_sheet_missing"};
  var financeSheet = ss.getSheetByName(FINANCE_SHEET);
  if (!financeSheet) financeSheet = ss.insertSheet(FINANCE_SHEET);
  _ensureFinanceHeaders_(financeSheet);

  var stateStore = PropertiesService.getScriptProperties();
  var duplicate = _financeDuplicatePayment_(financeSheet, tokens);
  if (duplicate) {
    if (String(duplicate.userId || "").trim() !== userId) {
      return {status:"error", message:"transaction_already_used", financeRow:duplicate.row};
    }
    var duplicateStatus = String(duplicate.status || "").trim().toUpperCase();
    if (duplicateStatus === "PENDING") {
      var recovered = _recoverPendingTransaction_(
        financeSheet, membersSheet, duplicate, payment, stateStore
      );
      if (recovered) return recovered;
      return {status:"error", message:"transaction_in_progress", financeRow:duplicate.row};
    }
    var duplicateMember = _findMemberRecord_(membersSheet, userId);
    if (duplicateStatus !== "APPROVED") {
      return {
        status:"error", message:"transaction_review_required",
        financeRow:duplicate.row, financeStatus:duplicateStatus,
        member:duplicateMember.record || null
      };
    }
    return {
      status:"ok", result:"duplicate", duplicate:true,
      financeRow:duplicate.row, member:duplicateMember.record || null
    };
  }

  var memberLookup = _findMemberRecord_(membersSheet, userId);
  if (memberLookup.count > 1) {
    return {status:"error", message:"duplicate_member_rows", userId:userId};
  }
  var previous = memberLookup.record;
  var previousExpire = previous ? _parseMemberDate(previous.expireDate) : null;
  var previousIsActive = !!(previous
    && previous.status === "ACTIVE"
    && previousExpire
    && previousExpire > new Date());
  // Keep active Premium users from silently losing Web access, but allow an
  // expired/KICKED Premium row to reactivate as Standard without a duplicate row.
  if (previousIsActive && previous.package === "WEB" && targetPackage === "CH") {
    return {status:"error", message:"web_to_channel_downgrade_not_allowed"};
  }
  var entryType = !previous
    ? "NEW"
    : (previous.package === "CH" && targetPackage === "WEB" ? "UPGRADE" : "RENEW");
  var stateKey = _transactionStateKey_(paymentId || transactionNo);
  var existingState = String(stateStore.getProperty(stateKey) || "").trim();
  if (existingState) {
    return {status:"error", message:"transaction_in_progress", state:existingState};
  }

  var now = new Date();
  var financeDate = dateText || Utilities.formatDate(now, "Asia/Bangkok", "dd/MM/yyyy");
  var financeTime = String(payment.time || Utilities.formatDate(now, "Asia/Bangkok", "HH:mm")).trim();
  var pendingNote = [
    "PENDING member+finance transaction",
    "source=" + source,
    "userId=" + userId,
    "package=" + targetPackage,
    "days=" + days,
    "months=" + calendarMonths,
    "entryType=" + entryType,
    "approvedBy=" + approvedBy,
    "financeDate=" + financeDate,
    "previousStatus=" + (previous ? previous.status : "NONE"),
    "previousPackage=" + (previous ? previous.package : ""),
    "previousStart=" + (previous ? previous.startDate : ""),
    "previousExpire=" + (previous ? previous.expireDate : "")
  ].join("; ");
  financeSheet.appendRow([
    financeDate, financeTime, userId, username,
    targetPackage, calendarMonths || Math.max(1, Math.round(days / 30)), receivedAmount,
    payment.payType || method, transactionNo,
    payment.receiver || payment.transferTo || "", payment.sender || "", "PENDING",
    entryType, source, paymentId, approvedBy, "", pendingNote
  ]);
  var financeRow = financeSheet.getLastRow();
  stateStore.setProperty(stateKey, "PENDING|" + financeRow);

  var saved;
  try {
    saved = saveMember(userId, username, days, String(payment.password || ""), targetPackage, calendarMonths);
  } catch (saveError) {
    _setFinanceTransactionState_(financeSheet, financeRow, "ERROR", entryType, source,
      paymentId, approvedBy, "", "Member save exception; manual review required");
    stateStore.deleteProperty(stateKey);
    return {status:"error", message:"member_save_failed", detail:String(saveError)};
  }
  if (!saved || saved.status !== "ok") {
    _setFinanceTransactionState_(financeSheet, financeRow, "ERROR", entryType, source,
      paymentId, approvedBy, "", "Member save failed: " + String(saved && saved.message || "unknown"));
    stateStore.deleteProperty(stateKey);
    return {status:"error", message:"member_save_failed", detail:String(saved && saved.message || "unknown")};
  }

  var afterLookup = _findMemberRecord_(membersSheet, userId);
  var after = afterLookup.record;
  var integrityOk = afterLookup.count === 1 && after && after.package === targetPackage
    && after.status === "ACTIVE" && after.startDate && after.expireDate;
  if (previous && previousIsActive && after && previous.startDate !== after.startDate) integrityOk = false;
  if (previous && previousIsActive && previous.package === "WEB" && previous.password
      && after && previous.password !== after.password) integrityOk = false;
  if (!integrityOk) {
    stateStore.setProperty(stateKey, "MEMBER_SAVED|" + financeRow);
    _setFinanceTransactionState_(financeSheet, financeRow, "REVIEW", entryType, source,
      paymentId, approvedBy, after ? after.expireDate : "",
      "Member saved but canonical re-read failed; do not retry approval");
    return {status:"error", message:"member_finance_review_required", member:after || null, financeRow:financeRow};
  }

  var approvedNote = "Approved by " + approvedBy + "; canonical member verified; transaction committed";
  _setFinanceTransactionState_(financeSheet, financeRow, "APPROVED", entryType, source,
    paymentId, approvedBy, after.expireDate, approvedNote);
  writeAuditLog(approvedBy, "PAYMENT_TRANSACTION", userId,
    "APPROVED:" + entryType + ":" + paymentId);
  stateStore.deleteProperty(stateKey);
  return {
    status:"ok", result:"approved", entryType:entryType,
    previousPackage:previous ? previous.package : "", package:after.package,
    member:after, financeRow:financeRow, password:after.password
  };
}

function approveManualMemberTransaction_(payment) {
  payment = payment || {};
  var userId = String(payment.userId || "").trim();
  var username = String(payment.username || "").trim();
  var targetPackage = _normalizePackage(payment.package || "CH");
  var approvedBy = String(payment.approvedBy || "").trim();
  var operationId = String(payment.operationId || payment.paymentId || "").trim();
  var calendarMonths = parseInt(payment.months, 10) || 0;
  var days = parseInt(payment.days || (calendarMonths * 30), 10);

  if (!userId) return {status:"error", message:"user_id_required"};
  if (targetPackage !== "CH" && targetPackage !== "WEB") {
    return {status:"error", message:"invalid_package"};
  }
  if (!approvedBy) return {status:"error", message:"approved_by_required"};
  if (!isFinite(days) || days <= 0) return {status:"error", message:"invalid_expire_days"};
  if (operationId.length < 5) return {status:"error", message:"manual_operation_id_required"};

  var ss = SpreadsheetApp.openById(SS_ID);
  var membersSheet = ss.getSheetByName(MEMBERS);
  if (!membersSheet) return {status:"error", message:"members_sheet_missing"};
  var financeSheet = ss.getSheetByName(FINANCE_SHEET);
  if (!financeSheet) financeSheet = ss.insertSheet(FINANCE_SHEET);
  _ensureFinanceHeaders_(financeSheet);

  var stateStore = PropertiesService.getScriptProperties();
  var duplicate = _financeDuplicatePayment_(financeSheet, _transactionIdTokens_(operationId));
  if (duplicate) {
    if (String(duplicate.userId || "").trim() !== userId) {
      return {status:"error", message:"transaction_already_used", financeRow:duplicate.row};
    }
    var duplicateStatus = String(duplicate.status || "").trim().toUpperCase();
    if (duplicateStatus === "PENDING") {
      var recovered = _recoverPendingTransaction_(
        financeSheet, membersSheet, duplicate,
        {userId:userId, paymentId:operationId, approvedBy:approvedBy}, stateStore
      );
      if (recovered) return recovered;
      return {status:"error", message:"transaction_in_progress", financeRow:duplicate.row};
    }
    if (duplicateStatus !== "APPROVED") {
      return {
        status:"error", message:"transaction_review_required",
        financeRow:duplicate.row, financeStatus:duplicateStatus
      };
    }
    return {status:"ok", result:"duplicate", duplicate:true, financeRow:duplicate.row};
  }

  var memberLookup = _findMemberRecord_(membersSheet, userId);
  if (memberLookup.count > 1) {
    return {status:"error", message:"duplicate_member_rows", userId:userId};
  }
  var previous = memberLookup.record;
  var previousExpire = previous ? _parseMemberDate(previous.expireDate) : null;
  var previousIsActive = !!(previous
    && previous.status === "ACTIVE"
    && previousExpire
    && previousExpire > new Date());
  var entryType = !previous
    ? "NEW"
    : (previous.package === "CH" && targetPackage === "WEB" ? "UPGRADE" : "RENEW");
  var stateKey = _transactionStateKey_(operationId);
  var existingState = String(stateStore.getProperty(stateKey) || "").trim();
  if (existingState) {
    return {status:"error", message:"transaction_in_progress", state:existingState};
  }

  var now = new Date();
  var financeDate = Utilities.formatDate(now, "Asia/Bangkok", "dd/MM/yyyy");
  var financeTime = Utilities.formatDate(now, "Asia/Bangkok", "HH:mm");
  var pendingNote = [
    "PENDING manual member+finance transaction",
    "source=MANUAL",
    "userId=" + userId,
    "package=" + targetPackage,
    "days=" + days,
    "months=" + calendarMonths,
    "entryType=" + entryType,
    "approvedBy=" + approvedBy,
    "financeDate=" + financeDate,
    "previousStatus=" + (previous ? previous.status : "NONE"),
    "previousPackage=" + (previous ? previous.package : ""),
    "previousStart=" + (previous ? previous.startDate : ""),
    "previousExpire=" + (previous ? previous.expireDate : "")
  ].join("; ");
  financeSheet.appendRow([
    financeDate, financeTime, userId, username,
    targetPackage, calendarMonths || Math.max(1, Math.round(days / 30)), "",
    "Manual", operationId, "", "", "PENDING",
    entryType, "MANUAL", operationId, approvedBy, "", pendingNote
  ]);
  var financeRow = financeSheet.getLastRow();
  stateStore.setProperty(stateKey, "PENDING|" + financeRow);

  var saved;
  try {
    saved = saveMember(userId, username, days, String(payment.password || ""), targetPackage, calendarMonths);
  } catch (saveError) {
    _setFinanceTransactionState_(financeSheet, financeRow, "ERROR", entryType, "MANUAL",
      operationId, approvedBy, "", "Member save exception; manual review required");
    stateStore.deleteProperty(stateKey);
    return {status:"error", message:"member_save_failed", detail:String(saveError)};
  }
  if (!saved || saved.status !== "ok") {
    _setFinanceTransactionState_(financeSheet, financeRow, "ERROR", entryType, "MANUAL",
      operationId, approvedBy, "", "Member save failed: " + String(saved && saved.message || "unknown"));
    stateStore.deleteProperty(stateKey);
    return {status:"error", message:"member_save_failed", detail:String(saved && saved.message || "unknown")};
  }

  var afterLookup = _findMemberRecord_(membersSheet, userId);
  var after = afterLookup.record;
  var integrityOk = afterLookup.count === 1 && after && after.package === targetPackage
    && after.status === "ACTIVE" && after.startDate && after.expireDate;
  if (previous && previousIsActive && after && previous.startDate !== after.startDate) integrityOk = false;
  if (previous && previousIsActive && previous.package === "WEB" && previous.password
      && targetPackage === "WEB" && after && previous.password !== after.password) integrityOk = false;
  if (!integrityOk) {
    stateStore.setProperty(stateKey, "MEMBER_SAVED|" + financeRow);
    _setFinanceTransactionState_(financeSheet, financeRow, "REVIEW", entryType, "MANUAL",
      operationId, approvedBy, after ? after.expireDate : "",
      "Member saved but canonical re-read failed; do not retry manual approval");
    return {status:"error", message:"member_finance_review_required", member:after || null, financeRow:financeRow};
  }

  _setFinanceTransactionState_(financeSheet, financeRow, "APPROVED", entryType, "MANUAL",
    operationId, approvedBy, after.expireDate,
    "Manual approval committed; canonical member verified");
  writeAuditLog(approvedBy, "MANUAL_MEMBER_APPROVAL", userId,
    "APPROVED:" + entryType + ":" + operationId);
  stateStore.deleteProperty(stateKey);
  return {
    status:"ok", result:"approved", entryType:entryType,
    package:after.package, member:after, financeRow:financeRow,
    password:after.password
  };
}

// ── saveMember ─────────────────────────────────────────────
function saveMember(userId, username, expireDays, password, pkg, expireMonths) {
  var ss     = SpreadsheetApp.openById(SS_ID);
  var sheet  = ss.getSheetByName(MEMBERS);
  var now    = new Date();
  var days   = parseInt(expireDays, 10);
  if (!isFinite(days) || days <= 0) {
    return {status:"error", message:"invalid_expire_days"};
  }
  var startStr = Utilities.formatDate(now, "Asia/Bangkok", "dd/MM/yyyy");
  var normalizedPackage = _normalizePackage(pkg);
  var requestedPassword = String(password || "").trim();

  var rows = sheet.getDataRange().getValues();
  for (var i = 1; i < rows.length; i++) {
    if (String(rows[i][C_USERID]) === String(userId)) {
      // Renewal: add purchased days after the current expiry when it is still
      // active. Expired/KICKED accounts restart from the admin approval time.
      var currentExpire = _parseMemberDate(rows[i][C_EXPIRE]);
      var currentStatus = String(rows[i][C_STATUS] || "").trim().toUpperCase();
      var currentIsActive = currentStatus === "ACTIVE"
        && currentExpire && currentExpire > now;
      var renewalBase = currentIsActive ? currentExpire : now;
      var expire = _addMembershipPeriod_(renewalBase, days, expireMonths);
      var expireStr = Utilities.formatDate(expire, "Asia/Bangkok", "dd/MM/yyyy");
      var currentPackage = _normalizePackage(rows[i][C_PACKAGE]);
      var currentPassword = String(rows[i][C_PASSWORD] || "").trim();
      var effectivePassword = "";

      // Same-package WEB renewals keep the existing password. Generate a
      // password only for a new WEB account or a CH -> WEB upgrade.
      if (normalizedPackage === "WEB") {
        effectivePassword = currentPackage === "WEB" && currentPassword
          ? currentPassword
          : requestedPassword;
        if (!effectivePassword) {
          return {status:"error", message:"web_password_required"};
        }
      }

      if (!currentIsActive) {
        sheet.getRange(i+1, C_START+1).setValue(startStr);
      }
      sheet.getRange(i+1, C_EXPIRE+1).setValue(expireStr);
      sheet.getRange(i+1, C_STATUS+1).setValue("ACTIVE");
      sheet.getRange(i+1, C_PASSWORD+1).setValue(effectivePassword);
      sheet.getRange(i+1, C_PACKAGE+1).setValue(normalizedPackage);
      // Force a fresh login only after the admin approves the renewal.
      sheet.getRange(i+1, C_TOKEN+1).setValue("");
      _revokeMemberSessions_(String(userId));
      writeAuditLog('Admin', 'RENEW', username, 'pkg:' + normalizedPackage);
      var renewalType = currentPackage === "CH" && normalizedPackage === "WEB" ? "UPGRADE" : "RENEW";
      return {
        status:"ok",
        result:"renewed",
        entryType:renewalType,
        previousPackage:currentPackage,
        package:normalizedPackage,
        password:effectivePassword,
        passwordPreserved:normalizedPackage === "WEB" && currentPackage === "WEB" && !!currentPassword,
        expireDate:expireStr
      };
    }
  }

  // New member
  if (normalizedPackage === "WEB" && !requestedPassword) {
    return {status:"error", message:"web_password_required"};
  }
  var expire = _addMembershipPeriod_(now, days, expireMonths);
  var expireStr = Utilities.formatDate(expire, "Asia/Bangkok", "dd/MM/yyyy");
  var newPassword = normalizedPackage === "WEB" ? requestedPassword : "";
  sheet.appendRow([
    userId, username, startStr, expireStr, "ACTIVE",
    0, newPassword, normalizedPackage, ""
  ]);
  writeAuditLog('Admin', 'APPROVE', username, 'pkg:' + normalizedPackage);
  return {
    status:"ok",
    result:"added",
    entryType:"NEW",
    previousPackage:"",
    package:normalizedPackage,
    password:newPassword,
    passwordPreserved:false,
    expireDate:expireStr
  };
}

// ── getMembers ─────────────────────────────────────────────
function getMembers() {
  var ss    = SpreadsheetApp.openById(SS_ID);
  var sheet = ss.getSheetByName(MEMBERS);
  var rows  = sheet.getDataRange().getValues();
  var now   = new Date();
  var members = [];
  // Batch every Sheet write instead of issuing one Range.setValue()/
  // _revokeMemberSessions_() call per row inline — with dozens of
  // non-active rows that used to mean dozens of full sessions-sheet scans
  // on every single getMembers() call, slow enough to blow past callers'
  // request timeouts (see _revokeMemberSessionsBulk_ for the other half).
  var statusUpdates = [];
  var tokenUpdates  = [];
  var revokeUserIds = [];
  // One full read of AuthSessions, reused for every row below — same
  // batching principle as the writes: avoid turning an O(1) sheet read
  // into an O(rows) one.
  var lastActiveByUser = _lastActiveByUser_();
  for (var i = 1; i < rows.length; i++) {
    if (!rows[i][C_USERID]) continue;
    var rawDate    = rows[i][C_EXPIRE];
    var expireDate = _parseMemberDate(rawDate);
    var savedStatus = String(rows[i][C_STATUS] || "").trim().toUpperCase();
    // A PENDING row (Google Login signup awaiting its first payment) has no
    // ExpireDate yet by design -- never recompute it via the usual date math,
    // and never strip its session token while still within
    // PENDING_SIGNUP_EXPIRY_DAYS of StartDate, or the member is locked out
    // before an admin ever gets to approve their first payment. Past that
    // window with still no payment, treat it like any other lapsed signup.
    var status = savedStatus === MEMBER_STATUS_PENDING
      ? (_isPendingSignupExpired_(rows[i][C_START], now) ? "EXPIRED" : savedStatus)
      : (savedStatus === "KICKED" || savedStatus === "BANNED")
        ? savedStatus
        : (expireDate && expireDate >= now ? "ACTIVE" : "EXPIRED");
    if (status !== savedStatus) {
      statusUpdates.push({row: i + 1, value: status});
    }
    // Expired/kicked/banned and non-WEB accounts must never retain a web
    // session token. PENDING (Google Login, not yet approved, still within
    // its signup window) keeps its token so the member can complete their
    // first payment.
    if (status !== MEMBER_STATUS_PENDING && (status !== "ACTIVE" || _normalizePackage(rows[i][C_PACKAGE]) !== "WEB")) {
      if (rows[i][C_TOKEN]) {
        tokenUpdates.push({row: i + 1, value: ""});
      }
      revokeUserIds.push(String(rows[i][C_USERID] || '').trim());
    }
    var lastActive = lastActiveByUser[_normalizeBindingUserId_(rows[i][C_USERID])];
    members.push({
      userId:     String(rows[i][C_USERID]),
      username:   String(rows[i][C_USERNAME]),
      startDate:  String(rows[i][C_START]),
      expireDate: expireDate
        ? Utilities.formatDate(expireDate, "Asia/Bangkok", "dd/MM/yyyy")
        : String(rawDate || ""),
      status:     status,
      package:    _normalizePackage(rows[i][C_PACKAGE]),
      lastActive: lastActive ? Utilities.formatDate(lastActive, "Asia/Bangkok", "yyyy-MM-dd'T'HH:mm:ss") : ""
    });
  }
  for (var s = 0; s < statusUpdates.length; s++) {
    sheet.getRange(statusUpdates[s].row, C_STATUS+1).setValue(statusUpdates[s].value);
  }
  for (var t = 0; t < tokenUpdates.length; t++) {
    sheet.getRange(tokenUpdates[t].row, C_TOKEN+1).setValue(tokenUpdates[t].value);
  }
  if (revokeUserIds.length) _revokeMemberSessionsBulk_(revokeUserIds);
  return members;
}

// ── verifyLogin (Password → return token) ─────────────────
function verifyLogin(password, deviceId, app) {
  if (!password) return {status:"error", message:"No password"};
  var ss    = SpreadsheetApp.openById(SS_ID);
  var sheet = ss.getSheetByName(MEMBERS);
  var rows  = sheet.getDataRange().getValues();
  var now   = new Date();

  for (var i = 1; i < rows.length; i++) {
    var storedPw = String(rows[i][C_PASSWORD] || "");
    if (!storedPw) continue;
    if (storedPw.trim() !== String(password).trim()) continue;

    var memberPackage = _normalizePackage(rows[i][C_PACKAGE]);
    if (memberPackage !== "WEB") {
      sheet.getRange(i+1, C_TOKEN+1).setValue("");
      return {status:"error", message:"web_access_required"};
    }

    var memberStatus = String(rows[i][C_STATUS] || "").trim().toUpperCase();
    if (memberStatus === "KICKED" || memberStatus === "BANNED" || memberStatus === "EXPIRED") {
      return {status:"error", message:memberStatus.toLowerCase()};
    }

    // Check expiry
    var rawDate    = rows[i][C_EXPIRE];
    var expireDate = _parseMemberDate(rawDate);
    if (!expireDate || expireDate < now) {
      return {status:"error", message:"expired"};
    }

    var memberId = String(rows[i][C_USERID] || '').trim();
    var deviceCheck = _verifyAndBindDevice_(memberId, deviceId, app);
    if (!deviceCheck.ok) return deviceCheck;

    // Preserve the legacy one-token behavior while recording a durable session.
    _revokeMemberSessions_(memberId);
    var token = Utilities.getUuid();
    var sessionResult = _createAuthSession_(token, memberId, deviceCheck, expireDate);
    if (sessionResult.status !== 'ok') return sessionResult;
    sheet.getRange(i+1, C_TOKEN+1).setValue(token);
    return {
      status:     "ok",
      token:      token,
      userId:     memberId,
      username:   String(rows[i][C_USERNAME]),
      package:    _normalizePackage(rows[i][C_PACKAGE]),
      expireDate: Utilities.formatDate(expireDate, "Asia/Bangkok", "dd/MM/yyyy"),
      deviceBound: !!deviceCheck.deviceBound,
      clientApp: deviceCheck.clientApp || 'web'
    };
  }

  return {status:"error", message:"wrong_password"};
}

// ── verifyToken ────────────────────────────────────────────
function verifyToken(token, deviceId, app, userId) {
  var safeToken = String(token || '').trim();
  if (!safeToken) return {status:"error", message:"No token"};
  var ss    = SpreadsheetApp.openById(SS_ID);
  var sheet = ss.getSheetByName(MEMBERS);
  var rows  = sheet.getDataRange().getValues();
  var now   = new Date();

  for (var i = 1; i < rows.length; i++) {
    if (String(rows[i][C_TOKEN] || '').trim() !== safeToken) continue;
    var memberId = String(rows[i][C_USERID] || '').trim();
    if (userId && _normalizeBindingUserId_(userId) !== _normalizeBindingUserId_(memberId)) {
      return {status:'error', message:'member_mismatch'};
    }
    var memberPackage = _normalizePackage(rows[i][C_PACKAGE]);
    if (memberPackage !== "WEB") {
      sheet.getRange(i+1, C_TOKEN+1).setValue("");
      _revokeMemberSessions_(memberId);
      return {status:"error", message:"web_access_required"};
    }
    var memberStatus = String(rows[i][C_STATUS] || "").trim().toUpperCase();
    if (memberStatus === "KICKED" || memberStatus === "BANNED" || memberStatus === "EXPIRED") {
      sheet.getRange(i+1, C_TOKEN+1).setValue("");
      _revokeMemberSessions_(memberId);
      return {status:"error", message:memberStatus.toLowerCase()};
    }
    var isPending = memberStatus === MEMBER_STATUS_PENDING;
    var rawDate    = rows[i][C_EXPIRE];
    var expireDate = _parseMemberDate(rawDate);
    // PENDING (Google Login signup, first payment not yet approved) has no
    // ExpireDate by design -- it is not an "expired" account on that basis,
    // but a PENDING session does go stale after PENDING_SIGNUP_EXPIRY_DAYS
    // with no payment, same window getMembers() enforces, so a forgotten
    // browser session can't sit valid forever.
    var pendingExpired = isPending && _isPendingSignupExpired_(rows[i][C_START], now);
    if (pendingExpired || (!isPending && (!expireDate || expireDate < now))) {
      sheet.getRange(i+1, C_TOKEN+1).setValue("");
      _revokeMemberSessions_(memberId);
      return {status:"error", message:"expired"};
    }

    var deviceCheck = _verifyAndBindDevice_(memberId, deviceId, app);
    if (!deviceCheck.ok) return deviceCheck;
    var sessionCheck = _verifyAuthSession_(safeToken, memberId, deviceCheck, isPending ? null : expireDate);
    if (sessionCheck.status !== 'ok') return sessionCheck;

    return {
      status:     "ok",
      userId:     memberId,
      username:   String(rows[i][C_USERNAME]),
      package:    _normalizePackage(rows[i][C_PACKAGE]),
      memberStatus: memberStatus,
      expireDate: (isPending || !expireDate) ? "" : Utilities.formatDate(expireDate, "Asia/Bangkok", "dd/MM/yyyy"),
      deviceBound: !!deviceCheck.deviceBound,
      clientApp: deviceCheck.clientApp || 'web'
    };
  }

  return {status:"error", message:"invalid_token"};
}

// ── Google ID token verification ────────────────────────────
// Uses Google's tokeninfo endpoint rather than a JWT/JWKS library: Apps
// Script has no built-in RS256 verification, and tokeninfo is Google's own
// supported lightweight path for a server-side ID-token check without a
// client library. One extra HTTPS round trip at login time is an acceptable
// cost for this.
function _verifyGoogleIdToken_(idToken) {
  var safeToken = String(idToken || '').trim();
  if (!safeToken) return {ok:false, message:'no_id_token'};
  var clientId = PropertiesService.getScriptProperties().getProperty('GOOGLE_OAUTH_CLIENT_ID');
  if (!clientId) return {ok:false, message:'google_login_not_configured'};

  var response;
  try {
    response = UrlFetchApp.fetch(
      'https://oauth2.googleapis.com/tokeninfo?id_token=' + encodeURIComponent(safeToken),
      {muteHttpExceptions: true}
    );
  } catch (e) {
    return {ok:false, message:'google_verify_failed'};
  }
  if (response.getResponseCode() !== 200) {
    return {ok:false, message:'invalid_google_token'};
  }

  var payload;
  try {
    payload = JSON.parse(response.getContentText());
  } catch (e) {
    return {ok:false, message:'invalid_google_response'};
  }
  if (!payload || !payload.sub || !payload.email) {
    return {ok:false, message:'invalid_google_payload'};
  }
  if (String(payload.aud) !== String(clientId)) {
    return {ok:false, message:'google_client_mismatch'};
  }
  if (payload.email_verified !== 'true' && payload.email_verified !== true) {
    return {ok:false, message:'google_email_unverified'};
  }
  return {ok:true, sub: String(payload.sub), email: String(payload.email).toLowerCase()};
}

// ── verifyGoogleLogin (Google ID token → return token) ───────
// Website-only signup path for members who never touch Telegram. A member
// who signs in with Google has no Telegram identity, so this issues a
// synthetic "G_<sub>" userId instead of a Telegram numeric id. First-time
// sign-in auto-creates a PENDING row with Package pre-set to "WEB" (the
// only package this path ever issues) and an empty ExpireDate; the member
// becomes a real ACTIVE WEB member only once an admin approves their first
// payment through the existing Telegram approval flow, exactly like every
// other WEB member -- this function never sets Package/Status to anything
// beyond WEB/PENDING itself.
//
// Called from inside doPost()'s script lock, so the read-then-append below
// (checking for an existing GoogleSub row before creating a new one) cannot
// race with a second concurrent sign-in for the same Google account.
function verifyGoogleLogin(idToken, deviceId, app) {
  var verified = _verifyGoogleIdToken_(idToken);
  if (!verified.ok) return {status:"error", message: verified.message};

  var ss    = SpreadsheetApp.openById(SS_ID);
  var sheet = ss.getSheetByName(MEMBERS);
  var rows  = sheet.getDataRange().getValues();
  var now   = new Date();

  for (var i = 1; i < rows.length; i++) {
    if (String(rows[i][C_GOOGLE_SUB] || '').trim() !== verified.sub) continue;

    var memberStatus = String(rows[i][C_STATUS] || "").trim().toUpperCase();
    if (memberStatus === "KICKED" || memberStatus === "BANNED") {
      return {status:"error", message: memberStatus.toLowerCase()};
    }
    var isPending = memberStatus === MEMBER_STATUS_PENDING;
    var rawDate    = rows[i][C_EXPIRE];
    var expireDate = _parseMemberDate(rawDate);
    if (!isPending && (!expireDate || expireDate < now)) {
      return {status:"error", message:"expired"};
    }

    var memberId = String(rows[i][C_USERID] || '').trim();
    // A returning Google sign-in is itself a fresh, strong re-authentication
    // -- rather than dead-ending on "expired" (which would just make the
    // visitor click Sign in with Google again anyway), refresh the signup
    // window so a PENDING member who was idle past PENDING_SIGNUP_EXPIRY_DAYS
    // can go straight back to payment instead of getting stuck.
    if (isPending && _isPendingSignupExpired_(rows[i][C_START], now)) {
      sheet.getRange(i+1, C_START+1).setValue(Utilities.formatDate(now, "Asia/Bangkok", "dd/MM/yyyy"));
    }
    var deviceCheck = _verifyAndBindDevice_(memberId, deviceId, app);
    if (!deviceCheck.ok) return deviceCheck;

    _revokeMemberSessions_(memberId);
    var token = Utilities.getUuid();
    var sessionResult = _createAuthSession_(token, memberId, deviceCheck, isPending ? null : expireDate);
    if (sessionResult.status !== 'ok') return sessionResult;
    sheet.getRange(i+1, C_TOKEN+1).setValue(token);
    return {
      status:       "ok",
      token:        token,
      userId:       memberId,
      username:     String(rows[i][C_USERNAME]),
      package:      _normalizePackage(rows[i][C_PACKAGE]),
      memberStatus: memberStatus,
      expireDate:   (isPending || !expireDate) ? "" : Utilities.formatDate(expireDate, "Asia/Bangkok", "dd/MM/yyyy"),
      deviceBound:  !!deviceCheck.deviceBound,
      clientApp:    deviceCheck.clientApp || 'web',
      isNewSignup:  false
    };
  }

  // No existing row for this Google account -- provision a new PENDING
  // member so the frontend can go straight to package selection and
  // payment through the same website payment endpoint every WEB renewal
  // already uses.
  var syntheticUserId = "G_" + verified.sub;
  var newDeviceCheck = _verifyAndBindDevice_(syntheticUserId, deviceId, app);
  if (!newDeviceCheck.ok) return newDeviceCheck;

  var newToken = Utilities.getUuid();
  sheet.appendRow([
    syntheticUserId,        // A UserID
    verified.email,         // B Username
    Utilities.formatDate(now, "Asia/Bangkok", "dd/MM/yyyy"), // C StartDate
    "",                      // D ExpireDate
    MEMBER_STATUS_PENDING,  // E Status
    0,                       // F CancelCount
    "",                      // G Password (Google Login members never get one)
    "WEB",                   // H Package
    newToken,                // I Token
    "",                      // J reserved -- legacy "DeviceID" column, left untouched
    verified.sub,            // K GoogleSub
    verified.email           // L GoogleEmail
  ]);
  var newSessionResult = _createAuthSession_(newToken, syntheticUserId, newDeviceCheck, null);
  if (newSessionResult.status !== 'ok') return newSessionResult;

  return {
    status:       "ok",
    token:        newToken,
    userId:       syntheticUserId,
    username:     verified.email,
    package:      "WEB",
    memberStatus: MEMBER_STATUS_PENDING,
    expireDate:   "",
    deviceBound:  !!newDeviceCheck.deviceBound,
    clientApp:    newDeviceCheck.clientApp || 'web',
    isNewSignup:  true
  };
}

// ── getPassword ────────────────────────────────────────────
function getPassword(userId) {
  if (!userId) return {status:"error"};
  var ss    = SpreadsheetApp.openById(SS_ID);
  var sheet = ss.getSheetByName(MEMBERS);
  var rows  = sheet.getDataRange().getValues();
  var now   = new Date();

  for (var i = 1; i < rows.length; i++) {
    if (String(rows[i][C_USERID]) !== String(userId)) continue;
    if (_normalizePackage(rows[i][C_PACKAGE]) !== "WEB") {
      sheet.getRange(i+1, C_TOKEN+1).setValue("");
      _revokeMemberSessions_(String(rows[i][C_USERID] || '').trim());
      return {status:"error", message:"web_access_required"};
    }
    var memberStatus = String(rows[i][C_STATUS] || "").trim().toUpperCase();
    if (memberStatus === "KICKED" || memberStatus === "BANNED" || memberStatus === "EXPIRED") {
      return {status:"error", message:memberStatus.toLowerCase()};
    }
    var rawDate    = rows[i][C_EXPIRE];
    var expireDate = _parseMemberDate(rawDate);
    if (!expireDate || expireDate < now) return {status:"error", message:"expired"};

    var pw = String(rows[i][C_PASSWORD] || "");
    if (!pw) return {status:"error", message:"no_password"};
    return {status:"ok", password: pw, package: _normalizePackage(rows[i][C_PACKAGE])};
  }
  return {status:"error", message:"not_found"};
}

// ── resetPassword ──────────────────────────────────────────
function resetPassword(username, newPassword) {
  if (!username || !newPassword) return {status:"error"};
  var ss    = SpreadsheetApp.openById(SS_ID);
  var sheet = ss.getSheetByName('Members');
  var rows  = sheet.getDataRange().getValues();
  var uname = username.replace("@","").toLowerCase();
  for (var i = 1; i < rows.length; i++) {
    var rowUserId = String(rows[i][C_USERID]   || "").trim();
    var rowUser   = String(rows[i][C_USERNAME] || "").replace("@","").toLowerCase().trim();
    if (rowUser !== uname && rowUserId !== uname) continue;
    if (_normalizePackage(rows[i][C_PACKAGE]) !== "WEB") {
      sheet.getRange(i+1, C_PASSWORD+1).setValue("");
      sheet.getRange(i+1, C_TOKEN+1).setValue("");
      _revokeMemberSessions_(rowUserId);
      return {status:"error", message:"web_access_required"};
    }
    sheet.getRange(i+1, C_PASSWORD+1).setValue(newPassword);
    sheet.getRange(i+1, C_TOKEN+1).setValue("");
    _revokeMemberSessions_(rowUserId);
    writeAuditLog('Admin', 'PASSWORD_RESET', uname, 'SUCCESS');
    return {
      status:   "ok",
      userId:   rowUserId,
      username: String(rows[i][C_USERNAME])
    };
  }
  return {status:"error", message:"not_found"};
}






















// ── updateMemberId ─────────────────────────────────────────
function updateMemberId(username, newId, newPassword) {
  if (!username || !newId) return {status:"error"};
  var ss      = SpreadsheetApp.openById(SS_ID);
  var sheet   = ss.getSheetByName(MEMBERS);
  var rows    = sheet.getDataRange().getValues();
  var uname   = username.replace("@","").toLowerCase();
  var nowStr  = Utilities.formatDate(new Date(), "Asia/Bangkok", "dd/MM/yyyy HH:mm");

  for (var i = 1; i < rows.length; i++) {
    var rowUser = String(rows[i][C_USERNAME] || "").replace("@","").toLowerCase();
    if (rowUser !== uname) continue;

    var oldId = String(rows[i][C_USERID]);

    // Update ID
    sheet.getRange(i+1, C_USERID+1).setValue(String(newId));
    // Update password if provided
    if (newPassword) sheet.getRange(i+1, C_PASSWORD+1).setValue(newPassword);
    // Clear token (force re-login)
    sheet.getRange(i+1, C_TOKEN+1).setValue("");
    _revokeMemberSessions_(oldId);
    // Log the change
    _logIdChange(ss, username, oldId, String(newId), nowStr);

    return {status:"ok", oldId: oldId, username: username};
  }
  return {status:"error", message:"not_found"};
}

function _logIdChange(ss, username, oldId, newId, changeDate) {
  try {
    var logSheet = ss.getSheetByName(LOG_SHEET);
    if (!logSheet) {
      logSheet = ss.insertSheet(LOG_SHEET);
      logSheet.appendRow(["Username", "Old_ID", "New_ID", "Changed_Date", "Changed_By"]);
    }
    logSheet.appendRow([username, oldId, newId, changeDate, "Admin"]);
  } catch(e) {}
}

// ── getBackupCSV ───────────────────────────────────────────
function getBackupCSV() {
  try {
    var ss    = SpreadsheetApp.openById(SS_ID);
    var sheet = ss.getSheetByName(MEMBERS);
    var rows  = sheet.getDataRange().getValues();

    var csv = [];
    // Header (exclude Token column for security)
    csv.push(["UserID","Username","StartDate","ExpireDate","Status","Package"].join(","));
    for (var i = 1; i < rows.length; i++) {
      if (!rows[i][C_USERID]) continue;
      csv.push([
        rows[i][C_USERID],
        rows[i][C_USERNAME],
        rows[i][C_START],
        rows[i][C_EXPIRE],
        rows[i][C_STATUS],
        rows[i][C_PACKAGE] || "CH"
      ].map(function(v){ return '"'+String(v).replace(/"/g,'""')+'"'; }).join(","));
    }

    return {status:"ok", csv: csv.join("\n")};
  } catch(e) {
    return {status:"error", message:e.toString()};
  }
}

// ── setupSheet ─────────────────────────────────────────────
function setupSheet() {
  var ss    = SpreadsheetApp.openById(SS_ID);
  var sheet = ss.getSheetByName(MEMBERS);

  // Ensure headers exist with new columns
  sheet.getRange(1, 1, 1, 9).setValues([[
    "UserID", "Username", "StartDate", "ExpireDate",
    "Status", "CancelCount", "Password", "Package", "Token"
  ]]);

  // Create Log sheet if needed
  if (!ss.getSheetByName(LOG_SHEET)) {
    var log = ss.insertSheet(LOG_SHEET);
    log.appendRow(["Username","Old_ID","New_ID","Changed_Date","Changed_By"]);
  }

  // Create Payment_History sheet if needed
  if (!ss.getSheetByName(PAY_SHEET)) {
    var pay = ss.insertSheet(PAY_SHEET);
    pay.appendRow(["Date","UserID","Username","Package","Months","Amount","PayType","Reference","Approved"]);
  }
}

// ── Weekly Auto Backup (Sunday 6AM) ───────────────────────
function weeklyBackup() {
  var result = getBackupCSV();
  if (result.status !== "ok") return;

  var filename = "Members_Backup_" + Utilities.formatDate(new Date(), "Asia/Bangkok", "yyyy-MM-dd") + ".csv";
  var folder   = DriveApp.getRootFolder(); // Root folder — change to specific folder if needed
  folder.createFile(filename, result.csv, MimeType.CSV);
  Logger.log("Backup saved: " + filename);
}

// ── Daily Duplicate UserID Check ──────────────────────────
function dailyDuplicateCheck() {
  var ss    = SpreadsheetApp.openById(SS_ID);
  var sheet = ss.getSheetByName(MEMBERS);
  var rows  = sheet.getDataRange().getValues();
  var seen  = {}, dups = [];
  for (var i = 1; i < rows.length; i++) {
    var uid = String(rows[i][C_USERID] || "");
    if (!uid) continue;
    if (seen[uid]) {
      dups.push(uid + " (rows " + (seen[uid]+1) + " & " + (i+1) + ")");
    } else {
      seen[uid] = i;
    }
  }

  if (dups.length > 0) {
    Logger.log("⚠️ Duplicate UserIDs found: " + dups.join(", "));
    // Note: To send Telegram notification, use UrlFetchApp with bot token
  }
}
function monthlyPasswordReset() {
  var BOT_TOKEN = PropertiesService.getScriptProperties().getProperty("BOT_TOKEN");
  if (!BOT_TOKEN) {
    Logger.log("BOT_TOKEN is not configured in Script Properties.");
    return;
  }

  var ss    = SpreadsheetApp.openById(SS_ID);
  var sheet = ss.getSheetByName("Members");
  var rows  = sheet.getDataRange().getValues();

  for (var i = 1; i < rows.length; i++) {
    if (String(rows[i][C_STATUS]).toUpperCase() !== "ACTIVE") continue;
    if (_normalizePackage(rows[i][C_PACKAGE]) !== "WEB") continue;

    var userId   = String(rows[i][C_USERID]);
    var username = rows[i][C_USERNAME] || "Member";

    // Password အသစ် generate
    var chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    var pw = "KMT-";
    for (var j = 0; j < 6; j++) pw += chars[Math.floor(Math.random()*chars.length)];
    pw += "-";
    for (var k = 0; k < 4; k++) pw += chars[Math.floor(Math.random()*chars.length)];

    // Sheet မှာ သိမ်း
    sheet.getRange(i+1, C_PASSWORD+1).setValue(pw);
    sheet.getRange(i+1, C_TOKEN+1).setValue("");

    // Bot က DM ပို့
    var msg = "🔄 *Password အသစ် (Monthly Reset)*\n\n"
            + "🔑 Password: `" + pw + "`\n\n"
            + "🌐 https://kyawmintun08.github.io/Japan-Auction-Car-Checker/\n\n"
            + "⚠️ Password ကို မည်သူ့ကိုမျှ မပေးပါနဲ့\n"
            + "   မျှဝေပါက Membership ပိတ်သိမ်းခံရမည်";

    try {
      var url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage";
      UrlFetchApp.fetch(url, {
        method: "post",
        contentType: "application/json",
        payload: JSON.stringify({
          chat_id:    userId,
          text:       msg,
          parse_mode: "Markdown"
        })
      });
    } catch(e) {
      Logger.log("DM failed for " + userId + ": " + e);
    }

    Utilities.sleep(500);
  }
}
// ═══════════════════════════════════════════
// PAYMENT QR HANDLERS (KPay / Wave / CB Bank)
// ═══════════════════════════════════════════

function getOrCreatePaymentConfig_() {
  const ss = SpreadsheetApp.openById(SS_ID);
  let sh = ss.getSheetByName('PaymentConfig');
  if (!sh) {
    sh = ss.insertSheet('PaymentConfig');
    sh.appendRow(['Method', 'FileID', 'UpdatedDate', 'UpdatedBy']);
    sh.getRange(1, 1, 1, 4)
      .setFontWeight('bold')
      .setBackground('#1a73e8')
      .setFontColor('#ffffff');
    sh.setColumnWidth(1, 80);
    sh.setColumnWidth(2, 320);
    sh.setColumnWidth(3, 160);
    sh.setColumnWidth(4, 120);
    sh.setFrozenRows(1);
  }
  return sh;
}

function getPaymentQR_(method) {
  const sh = getOrCreatePaymentConfig_();
  const data = sh.getDataRange().getValues();
  const m = String(method).toLowerCase().trim();
  for (let i = 1; i < data.length; i++) {
    if (String(data[i][0]).toLowerCase().trim() === m) {
      return {
        method: data[i][0],
        fileId: data[i][1],
        updated: data[i][2],
        updatedBy: data[i][3]
      };
    }
  }
  return null;
}

function setPaymentQR_(method, fileId, adminName) {
  const sh = getOrCreatePaymentConfig_();
  const data = sh.getDataRange().getValues();
  const now = new Date();
  const m = String(method).toLowerCase().trim();
  
  for (let i = 1; i < data.length; i++) {
    if (String(data[i][0]).toLowerCase().trim() === m) {
      sh.getRange(i + 1, 2).setValue(fileId);
      sh.getRange(i + 1, 3).setValue(now);
      sh.getRange(i + 1, 4).setValue(adminName || 'admin');
      return { ok: true, action: 'updated', method: m };
    }
  }
  
  sh.appendRow([m, fileId, now, adminName || 'admin']);
  return { ok: true, action: 'created', method: m };
}

// Manual test (Run > testPaymentQR_)
function testPaymentQR_() {
  const r1 = setPaymentQR_('kpay', 'TEST_FILE_ID', 'tun');
  Logger.log('SET: ' + JSON.stringify(r1));
  const r2 = getPaymentQR_('kpay');
  Logger.log('GET: ' + JSON.stringify(r2));
}






  
















































































































































    



    











      
















      









































































































































































  


// ── Read-only getData authentication ────────────────────────
// Startup data loading must validate the existing session without refreshing
// LastSeenAt, rebinding a device, revoking sessions, or migrating a legacy
// token. Login and the normal verifyToken action keep the original behavior.
function _verifyTokenForReadOnlyGetData_(token, deviceId, app, userId) {
  var safeToken = String(token || '').trim();
  if (!safeToken) return {status:'error', message:'No token'};
  var ss    = SpreadsheetApp.openById(SS_ID);
  var sheet = ss.getSheetByName(MEMBERS);
  var rows  = sheet.getDataRange().getValues();
  var now   = new Date();

  for (var i = 1; i < rows.length; i++) {
    if (String(rows[i][C_TOKEN] || '').trim() !== safeToken) continue;
    var memberId = String(rows[i][C_USERID] || '').trim();
    if (userId && _normalizeBindingUserId_(userId) !== _normalizeBindingUserId_(memberId)) {
      return {status:'error', message:'member_mismatch'};
    }
    var memberPackage = _normalizePackage(rows[i][C_PACKAGE]);
    if (memberPackage !== 'WEB') return {status:'error', message:'web_access_required'};

    var memberStatus = String(rows[i][C_STATUS] || '').trim().toUpperCase();
    if (memberStatus === 'KICKED' || memberStatus === 'BANNED' || memberStatus === 'EXPIRED') {
      return {status:'error', message:memberStatus.toLowerCase()};
    }

    var rawDate = rows[i][C_EXPIRE];
    var expireDate = _parseMemberDate(rawDate);
    if (!expireDate || expireDate < now) return {status:'error', message:'expired'};

    var deviceCheck = _verifyAndBindDevice_(memberId, deviceId, app, {readOnly:true});
    if (!deviceCheck.ok) return deviceCheck;
    var sessionCheck = _verifyAuthSession_(safeToken, memberId, deviceCheck, expireDate, {readOnly:true});
    if (sessionCheck.status !== 'ok') return sessionCheck;

    return {
      status: 'ok',
      userId: memberId,
      username: String(rows[i][C_USERNAME]),
      package: memberPackage,
      expireDate: Utilities.formatDate(expireDate, 'Asia/Bangkok', 'dd/MM/yyyy'),
      deviceBound: !!deviceCheck.deviceBound,
      clientApp: deviceCheck.clientApp || 'web'
    };
  }

  return {status:'error', message:'invalid_token'};
}

// ══════════════════════════════════════════════════════════════════════
// ONE-TIME BACKFILL: normalize Sheet1's historical "Model" column text.
// ------------------------------------------------------------------------
// Ports Python's normalize_model_name() (legacy_bot.py) to Apps Script so
// the ~5,000 existing rows match the same spelling/casing rules new bot
// entries now use: fixes typos, drops the brand-name prefix (chassis code
// already implies brand), merges the one confirmed synonym (HR-V -> Vezel),
// and PRESERVES genuinely distinct nameplates (Noah/Voxy, Hijet/Pixis/
// Sambar, etc.) and Hybrid/PHV trim suffixes as entered.
//
// These are plain functions, NOT wired into doPost — they only run when
// YOU execute them manually from the Apps Script editor (select the
// function in the toolbar dropdown, then click Run ▶). Nothing external
// can trigger them.
//
// HOW TO RUN THIS SAFELY:
//   1. Select "previewBackfillModelNames" in the function dropdown, click
//      Run. Open View > Executions (or check the new
//      "ModelBackfill_Preview" sheet tab it creates) to see every row
//      that WOULD change, old value -> new value. Nothing is written to
//      Sheet1 in this step.
//   2. Review the preview sheet. If it looks right, select
//      "backfillModelNames" in the dropdown and click Run. This is the
//      one that actually writes to Sheet1 — it first saves every
//      original value into a "ModelBackfill_Backup" sheet tab so you can
//      manually revert if something looks wrong.
// ══════════════════════════════════════════════════════════════════════

var MODEL_BRAND_WORDS = {
  "TOYOTA":1, "HONDA":1, "NISSAN":1, "NISSIAN":1, "MAZDA":1, "SUZUKI":1, "DAIHATSU":1,
  "SUBARU":1, "MITSUBISHI":1, "LEXUS":1, "HINO":1, "ISUZU":1, "UD":1
};
var MODEL_NOISE_WORDS = {
  "FREEZON":1, "FREEZONE":1, "KLANG9":1, "MAESOT":1, "44GATE":1, "WITE":1, "92000":1
};
var MODEL_TYPO_FIX = [
  ["NISSIAN", "NISSAN"], ["XTRAIL", "X-TRAIL"], ["WIAH", "WISH"], ["VIZEL", "VEZEL"],
  ["HONDAFIT", "FIT"], ["CX5", "CX-5"], ["JUAKE", "JUKE"], ["SABARU", "SUBARU"],
  ["FEILDER", "FIELDER"], ["VANNTEE", "VANETTE"], ["VANNETTE", "VANETTE"],
  ["VANETTEE", "VANETTE"], ["OUTLANDAR", "OUTLANDER"], ["MERA", "MIRA"],
  ["CRV", "CR-V"], ["SUCCEDD", "SUCCEED"], ["PARADO", "PRADO"]
];
var MODEL_KEEP_UPPER = {
  "CR-V":1, "CR-Z":1, "X-TRAIL":1, "HR-V":1, "LS460":1, "CT200H":1, "LX470":1, "UD":1,
  "CX-5":1, "CX-3":1, "CX-8":1, "RAV4":1, "C-HR":1, "NV200":1, "NV350":1, "LS":1, "AD":1,
  "RX":1, "NX":1, "GX":1, "LX":1, "IS":1, "ES":1, "GS":1, "UX":1, "LC":1
};

function normalizeModelNameGS(rawModel) {
  // Exact port of Python's normalize_model_name() — see legacy_bot.py.
  // Returns "" for empty/UNKNOWN input (caller should then leave the
  // original value untouched; there is no chassis-lookup fallback here).
  var m = String(rawModel || "").trim().toUpperCase();
  if (!m || m === "UNKNOWN" || m === "N/A" || m === "-" || m === "NONE") return "";

  for (var i = 0; i < MODEL_TYPO_FIX.length; i++) {
    var typo = MODEL_TYPO_FIX[i][0], fix = MODEL_TYPO_FIX[i][1];
    m = m.split(typo).join(fix); // replace ALL occurrences, like Python str.replace
  }

  var tokens = m.split(/\s+/).filter(function (t) { return t.length > 0; });
  tokens = tokens.filter(function (t) {
    return !MODEL_BRAND_WORDS[t] && !MODEL_NOISE_WORDS[t];
  });
  if (tokens.length === 0) return "";

  var joined = tokens.join(" ");
  if ((tokens.length === 1 && tokens[0] === "HR-V") ||
      joined === "HR-V" || joined === "HR-V (VEZEL)" || joined === "HR-V VEZEL") {
    tokens = ["VEZEL"];
  }

  var out = [];
  for (var j = 0; j < tokens.length; j++) {
    var t = tokens[j];
    if (MODEL_KEEP_UPPER[t]) {
      out.push(t);
    } else {
      out.push(t.charAt(0).toUpperCase() + t.slice(1).toLowerCase());
    }
  }
  return out.join(" ");
}

function _modelBackfillCompute_() {
  var ss = SpreadsheetApp.openById(SS_ID);
  var sheet = ss.getSheetByName('Sheet1');
  if (!sheet) throw new Error('Sheet1 not found');

  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();
  if (lastRow < 2) return { sheet: sheet, modelCol: -1, chassisCol: -1, changes: [], total: 0, same: 0, skipped: 0 };

  var headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0]
    .map(function (v) { return String(v || '').trim().toLowerCase(); });
  var modelCol = headers.indexOf('model');
  var chassisCol = headers.indexOf('chassis');
  if (modelCol < 0) throw new Error('Model column not found in Sheet1 headers');

  var numRows = lastRow - 1;
  var modelValues = sheet.getRange(2, modelCol + 1, numRows, 1).getValues();
  var chassisValues = chassisCol >= 0
    ? sheet.getRange(2, chassisCol + 1, numRows, 1).getValues()
    : null;

  var changes = []; // {row, chassis, oldVal, newVal}
  var same = 0, skipped = 0;
  for (var i = 0; i < numRows; i++) {
    var raw = modelValues[i][0];
    var rawStr = String(raw || '').trim();
    var normalized = normalizeModelNameGS(rawStr);
    var sheetRow = i + 2;
    var chassis = chassisValues ? chassisValues[i][0] : '';
    if (!normalized) { skipped++; continue; }
    if (normalized !== rawStr) {
      changes.push({ row: sheetRow, chassis: chassis, oldVal: rawStr, newVal: normalized });
    } else {
      same++;
    }
  }
  return { sheet: sheet, modelCol: modelCol, chassisCol: chassisCol, changes: changes,
           total: numRows, same: same, skipped: skipped };
}

function previewBackfillModelNames() {
  var result = _modelBackfillCompute_();
  var ss = SpreadsheetApp.openById(SS_ID);

  var summary = 'Model backfill PREVIEW — total rows: ' + result.total +
    ' | will change: ' + result.changes.length +
    ' | already correct: ' + result.same +
    ' | blank/UNKNOWN (left as-is): ' + result.skipped;
  Logger.log(summary);

  var previewSheetName = 'ModelBackfill_Preview';
  var previewSheet = ss.getSheetByName(previewSheetName);
  if (previewSheet) ss.deleteSheet(previewSheet);
  previewSheet = ss.insertSheet(previewSheetName);
  previewSheet.getRange(1, 1, 1, 5).setValues([['Sheet1 Row', 'Chassis', 'Old Model', 'New Model', summary]]);
  previewSheet.getRange(1, 1, 1, 5).setFontWeight('bold');

  if (result.changes.length > 0) {
    var out = result.changes.map(function (c) { return [c.row, c.chassis, c.oldVal, c.newVal, '']; });
    previewSheet.getRange(2, 1, out.length, 5).setValues(out);
  }
  previewSheet.autoResizeColumns(1, 4);

  return summary; // visible in Executions log when run from the editor
}

function backfillModelNames() {
  var result = _modelBackfillCompute_();
  var ss = SpreadsheetApp.openById(SS_ID);

  if (result.changes.length === 0) {
    Logger.log('No changes to apply — Model column already normalized.');
    return 'No changes to apply.';
  }

  // 1) Back up every value about to change, so this can be manually
  //    reverted (Sheet1 row -> original Model text) if needed.
  var backupSheetName = 'ModelBackfill_Backup';
  var backupSheet = ss.getSheetByName(backupSheetName);
  if (backupSheet) ss.deleteSheet(backupSheet);
  backupSheet = ss.insertSheet(backupSheetName);
  var stamp = Utilities.formatDate(new Date(), 'Asia/Bangkok', 'yyyy-MM-dd HH:mm:ss');
  backupSheet.getRange(1, 1, 1, 4).setValues([['Sheet1 Row', 'Chassis', 'Original Model (before backfill)', 'Backfilled at ' + stamp]]);
  backupSheet.getRange(1, 1, 1, 4).setFontWeight('bold');
  var backupRows = result.changes.map(function (c) { return [c.row, c.chassis, c.oldVal, '']; });
  backupSheet.getRange(2, 1, backupRows.length, 4).setValues(backupRows);
  backupSheet.autoResizeColumns(1, 3);

  // 2) Write the new Model values back, one row at a time is too slow for
  //    ~5k rows — batch into a single per-contiguous-block write where
  //    possible, otherwise fall back to individual setValue calls grouped
  //    by column (still one Range object, sparse rows use a full-column
  //    write built in memory to keep this to ONE Sheets API call).
  var sheet = result.sheet;
  var modelCol = result.modelCol;
  var numRows = result.total;
  var fullColumn = sheet.getRange(2, modelCol + 1, numRows, 1).getValues();
  for (var k = 0; k < result.changes.length; k++) {
    var c = result.changes[k];
    fullColumn[c.row - 2][0] = c.newVal;
  }
  sheet.getRange(2, modelCol + 1, numRows, 1).setValues(fullColumn);

  var summary = 'Model backfill APPLIED — changed ' + result.changes.length + ' of ' + result.total +
    ' rows. Original values saved in "' + backupSheetName + '" tab.';
  Logger.log(summary);
  return summary;
}

// ═══════════════════════════════════════════════════════════
//  Places directory — a standalone Name/Location/Phone
//  directory, unrelated to the existing Brokers/Requests broker
//  marketplace sheets. Admins add/remove entries via the bot
//  (/addplace, /removeplace); the website's Locations tab reads
//  them read-only through getPlaces (no server key needed, since
//  this is plain business-directory data, not member data).
// ═══════════════════════════════════════════════════════════
var PLACES_SHEET = "Places";
var PLACES_HEADERS = ["PlaceID", "Name", "Location", "Phone", "AddedBy", "AddedDate"];

function _ensurePlacesSheet_() {
  var ss = SpreadsheetApp.openById(SS_ID);
  var sheet = ss.getSheetByName(PLACES_SHEET);
  if (!sheet) {
    sheet = ss.insertSheet(PLACES_SHEET);
    sheet.appendRow(PLACES_HEADERS);
  } else if (sheet.getLastRow() < 1) {
    sheet.appendRow(PLACES_HEADERS);
  }
  return sheet;
}

function addPlace(payload) {
  payload = payload || {};
  var name = String(payload.name || "").trim();
  var location = String(payload.location || "").trim();
  var phone = String(payload.phone || "").trim();
  if (!name || !location || !phone) {
    return {status: "error", message: "name_location_phone_required"};
  }
  var addedBy = String(payload.addedBy || "").trim();
  var sheet = _ensurePlacesSheet_();
  var placeId = "P" + Utilities.getUuid().slice(0, 8).toUpperCase();
  var addedDate = Utilities.formatDate(new Date(), "Asia/Bangkok", "dd/MM/yyyy HH:mm");
  sheet.appendRow([placeId, name, location, phone, addedBy, addedDate]);
  return {
    status: "ok",
    place: {placeId: placeId, name: name, location: location, phone: phone, addedBy: addedBy, addedDate: addedDate}
  };
}

function getPlaces() {
  var sheet = _ensurePlacesSheet_();
  var rows = sheet.getDataRange().getValues();
  var places = [];
  for (var i = 1; i < rows.length; i++) {
    if (!rows[i][0]) continue;
    places.push({
      placeId: String(rows[i][0]),
      name: String(rows[i][1] || ""),
      location: String(rows[i][2] || ""),
      phone: String(rows[i][3] || ""),
      addedBy: String(rows[i][4] || ""),
      addedDate: String(rows[i][5] || "")
    });
  }
  return places;
}

function removePlace(placeId) {
  var target = String(placeId || "").trim();
  if (!target) return {status: "error", message: "place_id_required"};
  var sheet = _ensurePlacesSheet_();
  var rows = sheet.getDataRange().getValues();
  for (var i = 1; i < rows.length; i++) {
    if (String(rows[i][0]).trim() === target) {
      sheet.deleteRow(i + 1);
      return {status: "ok", result: "removed"};
    }
  }
  return {status: "error", message: "place_not_found"};
}
