// 本地缓存：草稿索引 + 单份内容。
// server 仍是 ID/同步权威；本地保证「不丢数据 + 秒开 + 离线续填」。
// 只依赖全局 dd.*（真机为环境全局；Node 单测注入 global.dd 打桩）。

var INDEX_KEY = 'draftIndex';
var DRAFT_PREFIX = 'draft:';
var LEGACY_KEY = 'myDrafts';

// 状态生命周期（与办公端/broker 同：草稿→已提交→待审核→已定稿）。
// 「已提交类」进入口页「已提交」分组、不可删；「只读类」整份不可再改。
var SUBMITTED_STATUSES = ['已提交', '待审核', '已定稿'];
var READONLY_STATUSES = ['待审核', '已定稿'];

/** 是否算「已提交」类（进已提交分组、不可删）：已提交/待审核/已定稿都算。 */
function isSubmittedStatus(s) { return SUBMITTED_STATUSES.indexOf(s) >= 0; }

/** 是否整份只读（已进入审核流程，不可再改）：待审核/已定稿。草稿/已提交仍可改。 */
function isReadonlyStatus(s) { return READONLY_STATUSES.indexOf(s) >= 0; }

/** 浅合并 a、b（b 覆盖 a）；不用 Object.assign 以免运行时差异。 */
function assign(a, b) {
  var o = {};
  var k;
  for (k in a) if (Object.prototype.hasOwnProperty.call(a, k)) o[k] = a[k];
  for (k in b) if (Object.prototype.hasOwnProperty.call(b, k)) o[k] = b[k];
  return o;
}

function getStorage(key) {
  return new Promise(function (resolve) {
    dd.getStorage({
      key: key,
      success: function (r) { resolve(r && r.data !== undefined ? r.data : null); },
      fail: function () { resolve(null); },
    });
  });
}

function setStorage(key, val) {
  return new Promise(function (resolve) {
    dd.setStorage({
      key: key, data: val,
      success: function () { resolve(true); },
      fail: function () { resolve(false); },
    });
  });
}

function removeStorage(key) {
  return new Promise(function (resolve) {
    dd.removeStorage({
      key: key,
      success: function () { resolve(true); },
      fail: function () { resolve(false); },
    });
  });
}

function newLocalId() {
  return 'local-' + Date.now() + '-' + Math.floor(Math.random() * 1e6);
}

function _pad(n) { return (n < 10 ? '0' : '') + n; }

/** 当前北京时间的 ISO 串（带 +08:00 偏移，无歧义）：如 "2026-08-15T10:30:00+08:00"。
 *  之前用 new Date().toISOString()（UTC/Z）→ 列表显示比北京晚 8 小时；改用本函数生成，
 *  办公端按偏移解析也正确。 */
function nowStamp() {
  var b = new Date(Date.now() + 8 * 3600 * 1000);   // 移到北京，再读 UTC 字段即北京各位
  return b.getUTCFullYear() + '-' + _pad(b.getUTCMonth() + 1) + '-' + _pad(b.getUTCDate())
    + 'T' + _pad(b.getUTCHours()) + ':' + _pad(b.getUTCMinutes()) + ':' + _pad(b.getUTCSeconds())
    + '+08:00';
}

/** 时间戳 → 北京时间 "MM-DD HH:mm"（列表展示）。兼容旧的 UTC/Z 与新的 +08:00：
 *  能解析就转北京；解析不了（如测试里的 't1'）退回原切片逻辑。 */
function fmtBeijingShort(s) {
  var d = new Date(s);
  if (isNaN(d.getTime())) {
    var t = String(s || '');
    return t.length >= 16 ? t.slice(5, 16).replace('T', ' ') : t;
  }
  var b = new Date(d.getTime() + 8 * 3600 * 1000);
  return _pad(b.getUTCMonth() + 1) + '-' + _pad(b.getUTCDate())
    + ' ' + _pad(b.getUTCHours()) + ':' + _pad(b.getUTCMinutes());
}

function _draftKey(id) { return DRAFT_PREFIX + id; }

function readIndex() {
  return getStorage(INDEX_KEY).then(function (v) { return Array.isArray(v) ? v : []; });
}

function writeIndex(list) { return setStorage(INDEX_KEY, list || []); }

/** 同一条判定：优先 serverId 相等，否则 id 互相命中（覆盖 local→server 迁移）。 */
function _same(a, b) {
  if (a.serverId && b.serverId) return a.serverId === b.serverId;
  if (a.id && b.id && a.id === b.id) return true;
  if (a.serverId && a.serverId === b.id) return true;
  if (b.serverId && b.serverId === a.id) return true;
  return false;
}

/** 按 _same 合并一条进索引（去重）；回写后返回整表。 */
function upsertIndexEntry(entry) {
  return readIndex().then(function (list) {
    var out = [];
    var merged = false;
    for (var i = 0; i < list.length; i++) {
      if (!merged && _same(list[i], entry)) {
        out.push(assign(list[i], entry));
        merged = true;
      } else {
        out.push(list[i]);
      }
    }
    if (!merged) out.push(entry);
    return writeIndex(out).then(function () { return out; });
  });
}

/** 写 draft:<id> 全量内容 + upsert 一条索引摘要。 */
function saveDraftLocal(draft) {
  return setStorage(_draftKey(draft.id), draft).then(function () {
    return upsertIndexEntry({
      id: draft.id,
      serverId: draft.serverId || '',
      category: draft.category || '',
      status: draft.status || '草稿',
      updatedAt: draft.updatedAt || '',
      dirty: !!draft.dirty,
      needsSync: !!draft.needsSync,
      submitted: isSubmittedStatus(draft.status),
    });
  }).then(function () { return draft; });
}

/** 读单份内容：先按 id 直取；缺失则按 serverId 在索引里找到 localId 再取。 */
function loadDraftLocal(id) {
  return getStorage(_draftKey(id)).then(function (d) {
    if (d) return d;
    return readIndex().then(function (list) {
      for (var i = 0; i < list.length; i++) {
        if (list[i].serverId === id && list[i].id && list[i].id !== id) {
          return getStorage(_draftKey(list[i].id));
        }
      }
      return null;
    });
  });
}

/** 首次服务端存盘成功后：把 serverId 关联到本地内容与索引。 */
function attachServerId(localId, serverId) {
  return getStorage(_draftKey(localId)).then(function (d) {
    var p = Promise.resolve();
    if (d) { d.serverId = serverId; p = setStorage(_draftKey(localId), d); }
    return p.then(function () {
      return upsertIndexEntry({ id: localId, serverId: serverId });
    });
  });
}

/** 提交成功后：删重内容缓存，索引留一条「已提交」轻记录。 */
function clearDraftContent(id) {
  return removeStorage(_draftKey(id)).then(function () {
    return upsertIndexEntry({ id: id, status: '已提交', submitted: true, dirty: false });
  });
}

/** 服务端摘要合并进本地索引：本地非 dirty 才让服务端覆盖状态。 */
function reconcileFromServer(rows) {
  return readIndex().then(function (list) {
    for (var i = 0; i < (rows || []).length; i++) {
      var r = rows[i];
      var found = null;
      for (var j = 0; j < list.length; j++) {
        if (list[j].serverId && list[j].serverId === r.survey_id) { found = list[j]; break; }
      }
      if (found) {
        if (!found.dirty) {
          found.category = r.category || found.category;
          found.status = r.status || found.status;
          found.updatedAt = r.updated_at || found.updatedAt;
          found.submitted = isSubmittedStatus(r.status) || found.submitted;
        }
      } else {
        list.push({
          id: r.survey_id, serverId: r.survey_id, category: r.category || '',
          status: r.status || '', updatedAt: r.updated_at || '',
          dirty: false, submitted: isSubmittedStatus(r.status),
        });
      }
    }
    return writeIndex(list).then(function () { return list; });
  });
}

/** 删一份草稿：删本地内容 + 索引条 + legacy myDrafts。回该条 serverId（供调用侧best-effort删服务端）。 */
function deleteDraft(id) {
  return Promise.all([loadDraftLocal(id), readIndex()]).then(function (arr) {
    var d = arr[0], list = arr[1];
    var serverId = (d && d.serverId) || '';
    if (!serverId) {   // 内容已清时从索引兜底取 serverId
      for (var i = 0; i < list.length; i++) {
        if (list[i].id === id) { serverId = list[i].serverId || ''; break; }
      }
    }
    var out = list.filter(function (e) {
      if (e.id === id) return false;
      if (serverId && e.serverId === serverId) return false;
      return true;
    });
    return removeStorage(_draftKey(id))
      .then(function () { return writeIndex(out); })
      .then(function () {
        if (!serverId) return null;
        return getStorage(LEGACY_KEY).then(function (ids) {
          if (!Array.isArray(ids)) return null;
          return setStorage(LEGACY_KEY, ids.filter(function (x) { return x !== serverId; }));
        });
      })
      .then(function () { return serverId; });
  });
}

/** 待自动补传的草稿索引条：用户点过暂存/提交但没成功（needsSync）、且未提交完成。
 *  只认 needsSync——填了一半没点保存的草稿（dirty 但 needsSync 假）不会被自动推上服务端。 */
function listPending() {
  return readIndex().then(function (list) {
    return list.filter(function (e) { return e.needsSync && !e.submitted; });
  });
}

/** 首次运行迁移：索引为空但有 v1 的 myDrafts，则据此种一份索引（内容仍靠服务端）。 */
function migrateLegacy() {
  return readIndex().then(function (list) {
    if (list.length > 0) return list;
    return getStorage(LEGACY_KEY).then(function (ids) {
      if (!Array.isArray(ids) || !ids.length) return list;
      var seeded = [];
      for (var i = 0; i < ids.length; i++) {
        seeded.push({
          id: ids[i], serverId: ids[i], category: '', status: '',
          updatedAt: '', dirty: false, submitted: false,
        });
      }
      return writeIndex(seeded).then(function () { return seeded; });
    });
  });
}

module.exports = {
  assign: assign,
  isSubmittedStatus: isSubmittedStatus, isReadonlyStatus: isReadonlyStatus,
  getStorage: getStorage, setStorage: setStorage, removeStorage: removeStorage,
  newLocalId: newLocalId, nowStamp: nowStamp, fmtBeijingShort: fmtBeijingShort,
  readIndex: readIndex, writeIndex: writeIndex, upsertIndexEntry: upsertIndexEntry,
  saveDraftLocal: saveDraftLocal, loadDraftLocal: loadDraftLocal,
  attachServerId: attachServerId, clearDraftContent: clearDraftContent,
  reconcileFromServer: reconcileFromServer, migrateLegacy: migrateLegacy,
  listPending: listPending, deleteDraft: deleteDraft,
};
