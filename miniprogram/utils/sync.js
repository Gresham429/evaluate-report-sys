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

function _payload(draft) {
  return {
    survey_id: draft.serverId || undefined,
    filler: draft.filler || '',
    category: draft.category || '',
    updated_at: draft.updatedAt || '',
    content: _content(draft),
  };
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

/** 同步一份草稿。回执 `{survey_id, submitted, photos}`；草稿不存在回 `{skipped:true}`。失败抛异常（草稿保持 needsSync）。 */
function syncOne(broker, store, id) {
  return store.loadDraftLocal(id).then(function (draft) {
    if (!draft) return { skipped: true };
    return _uploadPending(broker, store, draft).then(function () {
      return broker.request('saveDraft', _payload(draft)).then(function (r) {
        draft.serverId = r.survey_id;
        draft.status = '草稿';
        draft.dirty = false;
        draft.needsSync = false;
        return store.attachServerId(id, r.survey_id).then(function () {
          if (draft.pendingSubmit) {
            return broker.request('submit', { survey_id: r.survey_id })
              .then(function () { return store.clearDraftContent(id); })
              .then(function () {
                return { survey_id: r.survey_id, submitted: true, photos: draft.photos };
              });
          }
          return store.saveDraftLocal(draft).then(function () {
            return { survey_id: r.survey_id, submitted: false, photos: draft.photos };
          });
        });
      });
    });
  });
}

/** 后台补传：把所有 needsSync 草稿逐条 syncOne；任一条失败只计数、留着下次再试。单进程内 flushing 锁防重入。 */
function flush(broker, store) {
  if (flushing) return Promise.resolve({ skipped: true });
  flushing = true;
  var out = { synced: 0, submitted: 0, failed: 0 };
  return store.listPending().then(function (pending) {
    var chain = Promise.resolve();
    pending.forEach(function (entry) {
      chain = chain.then(function () {
        return syncOne(broker, store, entry.id)
          .then(function (r) {
            if (r.submitted) out.submitted++;
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

module.exports = { syncOne: syncOne, flush: flush };
