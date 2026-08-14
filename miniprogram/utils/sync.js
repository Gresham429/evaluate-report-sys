// 同步一份草稿到服务端：补传待上传照片 → saveDraft →（若有提交意图）submit。
// 同一条逻辑被两处复用：表单点「暂存/提交」即时调 syncOne（要回执做 UI）；
// 网络恢复/进页调 flush（后台把所有「needsSync」草稿逐条补传）。
// 幂等：saveDraft 按 survey_id upsert、submit 重复无害、已传照片即出 pendingPhotos 不重传。

var flushing = false;

function _content(draft) {
  return {
    basic: draft.basic || {}, gps: draft.gps || null,
    subjects: [], subject_levels: draft.subjectLevels || {},
    asset_conditions: draft.assetConditions || {}, photos: draft.photos || [],
  };
}

function _payload(draft, resolutions) {
  var p = {
    survey_id: draft.serverId || undefined,
    filler: draft.filler || '',
    category: draft.category || '',
    updated_at: draft.updatedAt || '',
    content: _content(draft),
  };
  // 双向同步：带上底版让 broker 走字段级三方合并（保住办公端回写的其它字段）；
  // 无底版（首个草稿/旧客户端）时不带 → broker 整份写入（向后兼容）。
  if (draft.base) p.base = draft.base;
  if (resolutions) p.resolutions = resolutions;
  return p;
}

/** 把冲突解决的选定值就地写回草稿内容（basic/subject_levels/asset_conditions），
 *  使本地显示与将写入服务端的一致。field 形如 'basic.client'。 */
function applyResolutions(draft, resolutions) {
  draft.basic = draft.basic || {};
  draft.subjectLevels = draft.subjectLevels || {};
  draft.assetConditions = draft.assetConditions || {};
  Object.keys(resolutions || {}).forEach(function (field) {
    var i = field.indexOf('.');
    if (i < 0) return;
    var section = field.slice(0, i), key = field.slice(i + 1);
    var target = section === 'basic' ? draft.basic
      : section === 'subject_levels' ? draft.subjectLevels
        : section === 'asset_conditions' ? draft.assetConditions : null;
    if (target) target[key] = resolutions[field];
  });
}

// 逐张补传待上传照片：成功的移入 photos 并即刻持久化（下次不再重传）；有失败则抛（该条保持 needsSync）。
function _uploadPending(broker, store, draft) {
  var pend = (draft.pendingPhotos || []).slice();
  if (!pend.length) return Promise.resolve(draft);
  var photos = (draft.photos || []).slice();
  var remaining = [];
  var chain = Promise.resolve();
  pend.forEach(function (p) {
    chain = chain.then(function () {
      if (remaining.length) { remaining.push(p); return; }   // 前面已失败，余下不再试
      return broker.request('uploadPhoto', { name: p.name, dataBase64: p.dataBase64 })
        .then(function (r) { photos.push(r.url); })
        .catch(function () { remaining.push(p); });
    });
  });
  return chain.then(function () {
    draft.photos = photos;
    draft.pendingPhotos = remaining;
    return store.saveDraftLocal(draft).then(function () {
      if (remaining.length) throw new Error('部分照片未传');
      return draft;
    });
  });
}

/** 同步一份草稿。回执 `{survey_id, submitted, photos, base}`；同字段冲突回
 *  `{conflict:true, conflicts, theirs_mtime}`（未写库、草稿保持 needsSync 待解决）；
 *  草稿不存在回 `{skipped:true}`。网络失败抛异常（草稿保持 needsSync）。
 *  `resolutions` 可选：冲突解决后带上二次提交。 */
function syncOne(broker, store, id, resolutions) {
  return store.loadDraftLocal(id).then(function (draft) {
    if (!draft) return { skipped: true };
    return _uploadPending(broker, store, draft).then(function () {
      return broker.request('saveDraft', _payload(draft, resolutions)).then(function (r) {
        // 冲突：broker 未写库、回冲突逐字段——不标已同步，交调用方（表单→冲突页）解决。
        if (r && r.status === 'conflict') {
          return { conflict: true, conflicts: r.conflicts || [], theirs_mtime: r.theirs_mtime || '' };
        }
        draft.serverId = r.survey_id;
        draft.status = '草稿';
        draft.dirty = false;
        draft.needsSync = false;
        // 合并成功 → 底版推进为「刚发送的内容」。数据安全：下次合并「我没改→取线上」
        // 会自动保住办公端后续改动，故无需回读服务端 merged（不额外多一趟请求、不改 broker）。
        draft.base = _content(draft);
        return store.attachServerId(id, r.survey_id).then(function () {
          if (draft.pendingSubmit) {
            return broker.request('submit', { survey_id: r.survey_id })
              .then(function () { return store.clearDraftContent(id); })
              .then(function () {
                return { survey_id: r.survey_id, submitted: true, photos: draft.photos };
              });
          }
          return store.saveDraftLocal(draft).then(function () {
            return { survey_id: r.survey_id, submitted: false, photos: draft.photos, base: draft.base };
          });
        });
      });
    });
  });
}

/** 冲突解决后二次保存：把选定值写回本地内容 → 带 base + resolutions 重发 saveDraft。
 *  回执同 syncOne（成功 `{survey_id,...}`；仍冲突则再回 `{conflict:true,...}`，罕见）。 */
function resolveConflict(broker, store, id, resolutions) {
  return store.loadDraftLocal(id).then(function (draft) {
    if (!draft) return { skipped: true };
    applyResolutions(draft, resolutions);
    return store.saveDraftLocal(draft).then(function () {
      return syncOne(broker, store, id, resolutions);
    });
  });
}

/** 后台补传：把所有 needsSync 草稿逐条 syncOne；任一条失败只计数、留着下次再试。单进程内 flushing 锁防重入。 */
function flush(broker, store) {
  if (flushing) return Promise.resolve({ skipped: true });
  flushing = true;
  var out = { synced: 0, submitted: 0, failed: 0, conflicts: 0 };
  return store.listPending().then(function (pending) {
    var chain = Promise.resolve();
    pending.forEach(function (entry) {
      chain = chain.then(function () {
        return syncOne(broker, store, entry.id)
          .then(function (r) {
            if (r.conflict) out.conflicts++;   // 后台补传遇冲突：留着 needsSync，待用户开草稿解决
            else if (r.submitted) out.submitted++;
            else if (!r.skipped) out.synced++;
          })
          .catch(function () { out.failed++; });
      });
    });
    return chain;
  }).then(function () {
    flushing = false;
    return out;
  }, function (e) {
    flushing = false;
    throw e;
  });
}

module.exports = {
  syncOne: syncOne, flush: flush,
  resolveConflict: resolveConflict, applyResolutions: applyResolutions,
};
