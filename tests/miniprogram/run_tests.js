/*
 * 钉钉小程序本地缓存 · Node 打桩验证（无需真机）。
 * 打桩全局 dd.*（内存 KV + 可切离线的 httpRequest）+ Page/getApp/getCurrentPages，
 * 驱动真实 store.js / broker.js / form.js / index.js 走现场场景。
 * 运行：node tests/miniprogram/run_tests.js  （退出码非 0 表示有断言失败）
 */
'use strict';
const path = require('path');

const clone = (x) => (x === undefined ? undefined : JSON.parse(JSON.stringify(x)));
const tick = async (n = 8) => { for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r)); };

// broker 三方合并的 JS 测试替身（对拍权威在 Python：src/serverless 的 merge.py + test_survey_merge.py）。
// 只为在无真机时驱动小程序的「带 base → 合并/冲突 → 解决」流程，返回形状与 broker 一致。
function mergeContentJS(base, mine, theirs) {
  const SECTIONS = ['basic', 'subject_levels', 'asset_conditions'];
  const merged = {}, conflicts = [];
  SECTIONS.forEach((sec) => {
    const b = base[sec] || {}, m = mine[sec] || {}, t = theirs[sec] || {};
    const keys = {}; [b, m, t].forEach((dd_) => Object.keys(dd_).forEach((k) => { keys[k] = 1; }));
    const out = {};
    Object.keys(keys).forEach((k) => {
      const bv = b[k], mv = m[k], tv = t[k];
      let chosen;
      if (mv === bv) chosen = tv;
      else if (tv === bv) chosen = mv;
      else if (mv === tv) chosen = mv;
      else { conflicts.push({ field: sec + '.' + k, base: bv, mine: mv, theirs: tv }); chosen = mv; }
      if (chosen !== undefined && chosen !== null) out[k] = chosen;
    });
    merged[sec] = out;
  });
  ['subjects', 'photos', 'gps'].forEach((sec) => { merged[sec] = theirs[sec]; });
  return { merged, conflicts };
}

// owners 并集测试替身（对拍权威在 broker store._union_owners）。
function unionOwnersJS(existing, incoming, filler) {
  const out = [];
  [existing || [], incoming || [], filler ? [filler] : []].forEach((lst) =>
    lst.forEach((x) => { if (x && out.indexOf(x) < 0) out.push(x); }));
  return out;
}

let PASS = 0, FAIL = 0;
function ok(cond, msg) { if (cond) { PASS++; } else { FAIL++; console.log('  ✗ FAIL: ' + msg); } }
function eq(a, b, msg) { ok(JSON.stringify(a) === JSON.stringify(b), msg + ` (got ${JSON.stringify(a)}, want ${JSON.stringify(b)})`); }

// ---- server 打桩 ----
function makeServer() {
  const state = { seq: 0, drafts: {}, uploads: 0 };
  function route(req) {
    const a = req.action, p = req.payload || {};
    if (a === 'uploadPhoto') {
      state.uploads++;
      return { url: 'https://dl/' + (p.name || 'x') + '?len=' + String(p.dataBase64 || '').length,
        name: p.name };
    }
    if (a === 'saveDraft') {
      const existed = p.survey_id ? state.drafts[p.survey_id] : null;
      // owners 并集：传了 → 与线上并集（filler 恒在）；没传 → 保留线上现状（新记录兜底 [filler]）。
      const prevOwners = existed ? (existed.owners || []) : [];
      const owners = p.owners ? unionOwnersJS(prevOwners, p.owners, p.filler)
        : (existed ? (prevOwners.length ? prevOwners : (p.filler ? [p.filler] : []))
          : (p.filler ? [p.filler] : []));
      // 双向同步：带 base 且行已存在 → 走三方合并（同 broker）；否则整份写入。
      if (p.base && existed) {
        const r = mergeContentJS(p.base, clone(p.content), existed.content || {});
        let unresolved = r.conflicts;
        if (p.resolutions) {
          unresolved = [];
          r.conflicts.forEach((c) => {
            if (Object.prototype.hasOwnProperty.call(p.resolutions, c.field)) {
              const dot = c.field.indexOf('.');
              const sec = c.field.slice(0, dot), key = c.field.slice(dot + 1);
              r.merged[sec] = r.merged[sec] || {};
              r.merged[sec][key] = p.resolutions[c.field];
            } else unresolved.push(c);
          });
        }
        if (unresolved.length) {
          return { status: 'conflict', conflicts: unresolved, theirs_mtime: existed.updated_at || '' };
        }
        state.drafts[p.survey_id] = { category: p.category, content: r.merged, filler: p.filler,
          status: existed.status || '草稿', updated_at: p.updated_at, owners: owners };
        return { survey_id: p.survey_id };
      }
      const sid = p.survey_id || ('srv-' + (++state.seq));
      state.drafts[sid] = { category: p.category, content: clone(p.content), filler: p.filler,
        status: (state.drafts[sid] && state.drafts[sid].status) || '草稿', updated_at: p.updated_at,
        owners: owners };
      return { survey_id: sid };
    }
    if (a === 'listSurveys') {
      const surveys = Object.keys(state.drafts)
        .filter((sid) => state.drafts[sid].filler === p.filler)
        .map((sid) => ({ survey_id: sid, status: state.drafts[sid].status,
          category: state.drafts[sid].category, updated_at: state.drafts[sid].updated_at }));
      return { surveys };
    }
    if (a === 'submit') { if (state.drafts[p.survey_id]) state.drafts[p.survey_id].status = '已提交'; return { ok: true }; }
    if (a === 'deleteDraft') { delete state.drafts[p.survey_id]; return { ok: true }; }
    if (a === 'loadDraft') {
      const d = state.drafts[p.survey_id] || {};
      return { category: d.category || '', content: d.content || {}, status: d.status || '',
        updated_at: d.updated_at || '', owners: d.owners || [] };
    }
    if (a === 'prefillGeo') return {
      address: '杭州市西湖区某路', bus_stops: ['A站', 'B站'],
      facilities: ['学校', '医院'], nearest_metro: { name: '龙翔桥', distance_m: 300 },
      center: { name: '西湖区政府', distance_m: 3500 },
      highway: { name: '留下收费站', distance_m: 2100 },
      parking: { count: 4, nearest_m: 120 },
      water: { name: '西溪湿地', distance_m: 800 },
      roads: ['文一路', '古墩路'],
    };
    if (a === 'whoami') return { userid: 'u1', name: '薛焱' };
    return {};
  }
  return { state, route };
}

// ---- dd 打桩 ----
function installEnv(server) {
  const kv = {};
  const env = { kv, offline: false, spies: { toast: [], navBack: 0, reLaunch: [], navTo: [] } };
  global.dd = {
    getStorage: ({ key, success, fail }) => {
      if (Object.prototype.hasOwnProperty.call(kv, key)) success({ data: clone(kv[key]) });
      else fail({ errorMessage: 'no such key' });
    },
    setStorage: ({ key, data, success }) => { kv[key] = clone(data); success && success(); },
    removeStorage: ({ key, success }) => { delete kv[key]; success && success(); },
    getLocation: ({ success }) => success({ latitude: 30.25, longitude: 120.21 }),
    chooseImage: ({ count, success }) =>
      success({ filePaths: ['/t/a.jpg', '/t/b.jpg'].slice(0, count || 9) }),
    compressImage: ({ apFilePaths, success }) => success({ apFilePaths }),
    getFileSystemManager: () => ({
      readFile: ({ filePath, success }) => success({ data: 'B64(' + filePath + ')' }),
    }),
    onNetworkStatusChange: () => {},
    confirm: ({ success }) => success({ confirm: true }),   // 删除确认框：默认点「删除」
    showToast: (o) => env.spies.toast.push(o),
    navigateBack: () => { env.spies.navBack++; },
    reLaunch: (o) => env.spies.reLaunch.push(o),
    navigateTo: (o) => env.spies.navTo.push(o),
    getAuthCode: ({ success }) => success({ authCode: 'code' }),
    httpRequest: ({ data, success, fail }) => {
      if (env.offline) { fail({ errorMessage: 'net' }); return; }
      success({ status: 200, data: server.route(JSON.parse(data)) });
    },
  };
  return env;
}

// ---- Page/getApp/getCurrentPages 打桩 ----
let lastCfg = null;
global.Page = (cfg) => { lastCfg = cfg; };
// 单例 app（贴真机：getApp() 全程返回同一对象），好让 form.js 与 conflict.js 共享
// globalData.pendingConflict（冲突跳转的传参）。
const APP = { globalData: { filler: 'u1', fillerName: '薛焱', BASE_URL: '', pendingConflict: null } };
global.getApp = () => APP;
global.getCurrentPages = () => [{}];               // length 1 → 提交后走 reLaunch
global.setTimeout = (fn) => { fn(); return 0; };    // 自动退出回调同步执行，便于断言

// setData 路径解析：支持 a.b.c、a[0]、a[0].b 混合（贴真机 setData 语义）。
function _pathTokens(k) {
  return k.replace(/\[(\d+)\]/g, '.$1').split('.')
    .filter((s) => s !== '')
    .map((s) => (/^\d+$/.test(s) ? parseInt(s, 10) : s));
}
function applySetData(data, patch) {
  for (const k of Object.keys(patch)) {
    const toks = _pathTokens(k);
    if (toks.length === 1) { data[toks[0]] = patch[k]; continue; }
    let o = data;
    for (let i = 0; i < toks.length - 1; i++) {
      const t = toks[i];
      if (o[t] == null || typeof o[t] !== 'object') o[t] = (typeof toks[i + 1] === 'number') ? [] : {};
      o = o[t];
    }
    o[toks[toks.length - 1]] = patch[k];
  }
}
function makePage(cfg) {
  const page = Object.create(cfg);
  page.data = clone(cfg.data);
  page.setData = function (patch) { applySetData(page.data, patch); };
  return page;
}

// 需在 installEnv 之后再 require（模块顶层 getApp()）
const server = makeServer();
let env = installEnv(server);
const store = require(path.join(__dirname, '../../miniprogram/utils/store.js'));
const sync = require(path.join(__dirname, '../../miniprogram/utils/sync.js'));
const broker = require(path.join(__dirname, '../../miniprogram/utils/broker.js'));
require(path.join(__dirname, '../../miniprogram/pages/form/form.js'));
const formCfg = lastCfg;
require(path.join(__dirname, '../../miniprogram/pages/index/index.js'));
const indexCfg = lastCfg;
require(path.join(__dirname, '../../miniprogram/pages/capture/capture.js'));
const captureCfg = lastCfg;
require(path.join(__dirname, '../../miniprogram/pages/factors/factors.js'));
const factorsCfg = lastCfg;
const FACTORS = require(path.join(__dirname, '../../miniprogram/factors.js'));

function resetEnv() { env = installEnv(server); server.state.seq = 0; server.state.drafts = {}; }

async function main() {
  // ===== A. store.js 单元 =====
  console.log('A. store.js 缓存核心');
  resetEnv();
  env.kv.myDrafts = ['srv-A', 'srv-B'];
  let idx = await store.migrateLegacy();
  eq(idx.length, 2, 'A1 migrateLegacy 从 myDrafts 种两条');
  ok(idx[0].serverId === 'srv-A' && idx[0].id === 'srv-A', 'A1 迁移条 serverId/id 对齐');

  resetEnv();
  await store.saveDraftLocal({ id: 'local-1', category: '商业', basic: { a: '1' }, gps: null,
    updatedAt: '2026-07-20T01:00:00Z', dirty: true });
  let d = await store.loadDraftLocal('local-1');
  eq(d.basic.a, '1', 'A2 saveDraftLocal/loadDraftLocal 内容往返');
  idx = await store.readIndex();
  ok(idx.length === 1 && idx[0].dirty === true, 'A2 索引一条且 dirty');

  await store.attachServerId('local-1', 'srv-1');
  idx = await store.readIndex();
  ok(idx.length === 1 && idx[0].serverId === 'srv-1' && idx[0].id === 'local-1', 'A3 attachServerId 不产生重复条');
  d = await store.loadDraftLocal('srv-1');
  eq(d && d.basic.a, '1', 'A3 按 serverId 也能取到本地内容');

  await store.clearDraftContent('local-1');
  d = await store.loadDraftLocal('local-1');
  ok(d === null, 'A4 clearDraftContent 删除重内容');
  idx = await store.readIndex();
  ok(idx[0].submitted === true && idx[0].status === '已提交', 'A4 索引留「已提交」轻记录');

  resetEnv();
  await store.writeIndex([
    { id: 'l8', serverId: 'srv-8', category: '办公', status: '未同步', updatedAt: 't0', dirty: true, submitted: false },
    { id: 'l9', serverId: 'srv-9', category: '住宅', status: '草稿', updatedAt: 't0', dirty: false, submitted: false },
  ]);
  await store.reconcileFromServer([
    { survey_id: 'srv-8', category: 'X', status: '已提交', updated_at: 't3' },
    { survey_id: 'srv-9', category: '住宅', status: '已提交', updated_at: 't3' },
    { survey_id: 'srv-new', category: '农用', status: '草稿', updated_at: 't3' },
  ]);
  idx = await store.readIndex();
  const e8 = idx.find((x) => x.serverId === 'srv-8');
  const e9 = idx.find((x) => x.serverId === 'srv-9');
  const eNew = idx.find((x) => x.serverId === 'srv-new');
  ok(e8.category === '办公' && e8.submitted === false, 'A5 dirty 条不被服务端覆盖');
  ok(e9.submitted === true && e9.status === '已提交', 'A5 非 dirty 条被服务端更新');
  ok(!!eNew, 'A5 服务端新条被并入');

  // ===== B. 表单现场流程（真实 form.js + broker.js）=====
  console.log('B. 表单现场流程');
  resetEnv();
  const p1 = makePage(formCfg);
  p1.onLoad({});
  const lid = p1.data.localId;
  ok(/^local-/.test(lid), 'B0 新建即生成本地 id');
  p1.onField({ currentTarget: { dataset: { key: 'client' } }, detail: { value: '张三' } });
  p1.onCategory({ detail: { value: 2 } });   // 商业
  await tick();
  ok(p1.data.dirty === true, 'B1 改动后 dirty');
  d = await store.loadDraftLocal(lid);
  eq(d.basic.client, '张三', 'B1 改动即本地存盘');

  // “杀进程重开”：新 page 对象、同一 KV
  const p2 = makePage(formCfg);
  p2.onLoad({ draftId: lid });
  await tick();
  eq(p2.data.form.basic.client, '张三', 'B2 重开后从本地恢复内容');
  eq(p2.data.form.category, '商业', 'B2 类别恢复');
  ok(p2.data.dirty === true && p2.data.localId === lid, 'B2 保持未同步 + 同一 localId');

  // 断网暂存：不丢、dirty、offline
  env.offline = true;
  p2.onSave();
  await tick();
  ok(p2.data.offline === true && p2.data.dirty === true, 'B3 断网暂存 → offline + 仍 dirty');
  ok(p2.data.survey_id === '', 'B3 断网未拿到 serverId');
  d = await store.loadDraftLocal(lid);
  eq(d.basic.client, '张三', 'B3 断网内容仍在本机');

  // 联网暂存：拿 serverId、synced、索引去重
  env.offline = false;
  p2.onSave();
  await tick();
  ok(/^srv-/.test(p2.data.survey_id), 'B4 联网暂存拿到 serverId');
  ok(p2.data.serverStatus === '草稿' && p2.data.dirty === false && p2.data.offline === false, 'B4 状态=草稿 synced');
  idx = await store.readIndex();
  const mine = idx.filter((x) => x.id === lid || x.serverId === p2.data.survey_id);
  ok(mine.length === 1 && mine[0].serverId === p2.data.survey_id, 'B4 索引只一条（local→server 去重）');

  // 提交：服务端已提交、清本地内容、toast、自动退出
  const sid = p2.data.survey_id;
  p2.onSubmit();
  await tick();
  eq(server.state.drafts[sid].status, '已提交', 'B5 服务端标记已提交');
  ok(p2.data.serverStatus === '已提交' && p2.data.dirty === false, 'B5 前端状态已提交');
  ok(env.spies.toast.length >= 1, 'B5 弹出提交成功 toast');
  ok(env.spies.reLaunch.length >= 1 || env.spies.navBack >= 1, 'B5 自动退出（reLaunch/navigateBack）');
  d = await store.loadDraftLocal(lid);
  ok(d === null, 'B5 提交后清除本地重内容');
  idx = await store.readIndex();
  ok(idx.find((x) => x.id === lid).submitted === true, 'B5 索引留已提交轻记录');

  // ===== C. 入口页对账（真实 index.js）=====
  console.log('C. 入口页离线秒开 + 联网对账');
  resetEnv();
  await store.writeIndex([{ id: 'lx', serverId: 'srv-x', category: '农用', status: '草稿',
    updatedAt: '2026-07-20T01:00:00Z', dirty: false, submitted: false }]);
  server.state.drafts['srv-x'] = { category: '农用', status: '已提交', content: {}, filler: 'u1', updated_at: '2026-07-20T02:00:00Z' };
  const ix = makePage(indexCfg);
  ix.onShow();
  await tick();
  eq(ix.data.drafts.length, 0, 'C1 对账后该条转已提交、离开未提交区');
  eq(ix.data.submittedGroups.length, 1, 'C1 已提交分组 1 组');
  eq(ix.data.submittedGroups[0].category, '农用', 'C1 分组类别=农用（联网对账刷成已提交）');

  // 离线：仍显示本地
  resetEnv();
  await store.writeIndex([{ id: 'ly', serverId: 'srv-y', category: '办公', status: '草稿',
    updatedAt: 't', dirty: false, submitted: false }]);
  env.offline = true;
  const ix2 = makePage(indexCfg);
  ix2.onShow();
  await tick();
  eq(ix2.data.drafts.length, 1, 'C2 离线仍从本地渲染');
  eq(ix2.data.drafts[0].status, '草稿', 'C2 离线保留本地状态');

  // ===== D. 在线拍照走全链路（form → capture → 提交带照片）=====
  console.log('D. 在线拍照 + 现场采集页');
  resetEnv();
  const fpD = makePage(formCfg);
  fpD.onLoad({});
  const lidD = fpD.data.localId;
  fpD.onCategory({ detail: { value: 2 } });   // 商业
  await tick();
  fpD.onCapture();
  await tick();
  ok(env.spies.navTo.length >= 1, 'D0 表单跳现场采集页');
  const capD = makePage(captureCfg);
  capD.onLoad({ draftId: lidD });
  await tick();
  eq(capD.data.form ? 0 : capD.data.localId === lidD, true, 'D1 采集页载入同一 localId');
  capD.onChoose();
  await tick();
  eq(capD.data.photos.length, 2, 'D1 在线拍 2 张即上传得 2 URL');
  eq(capD.data.pending.length, 0, 'D1 无待传');
  capD.onDone();
  await tick();
  fpD.onShow();
  await tick();
  eq(fpD.data.photos.length, 2, 'D2 返回表单 onShow 拉到 2 张照片');
  fpD.onSubmit();
  await tick();
  const dSubmitted = Object.keys(server.state.drafts).map((k) => server.state.drafts[k])
    .find((x) => x.status === '已提交');
  eq((dSubmitted.content.photos || []).length, 2, 'D2 提交后服务端 content.photos 含 2 URL');

  // ===== E. 离线拍照 + 离线提交 → 联网自动补传并提交 =====
  console.log('E. 离线采集 + 联网自动补传');
  resetEnv();
  const fpE = makePage(formCfg);
  fpE.onLoad({});
  const lidE = fpE.data.localId;
  fpE.onCategory({ detail: { value: 0 } });   // 农用
  await tick();
  env.offline = true;
  const capE = makePage(captureCfg);
  capE.onLoad({ draftId: lidE });
  await tick();
  capE.onChoose();          // 离线：上传失败入待传
  await tick();
  eq(capE.data.pending.length, 2, 'E1 离线拍照入待传队列（不丢）');
  eq(capE.data.photos.length, 0, 'E1 离线未产生已传 URL');
  capE.onDone();
  await tick();
  fpE.onShow();             // onShow 会触发 flush，但此时离线且 needsSync 假 → 不推
  await tick();
  fpE.onSubmit();           // 离线提交 → needsSync/pendingSubmit 置真，本机留
  await tick();
  ok(fpE.data.offline === true, 'E2 离线提交 → offline');
  let pend = await store.listPending();
  eq(pend.length, 1, 'E2 有一条待补传（needsSync）');
  // 联网 → flush 自动补传照片 + 暂存 + 提交
  env.offline = false;
  const outE = await sync.flush(broker, store);
  await tick();
  eq(outE.submitted, 1, 'E3 联网 flush 自动提交 1 条');
  const eSubmitted = Object.keys(server.state.drafts).map((k) => server.state.drafts[k])
    .find((x) => x.status === '已提交');
  eq((eSubmitted.content.photos || []).length, 2, 'E3 补传后服务端含 2 照片 URL');
  const eLocal = await store.loadDraftLocal(lidE);
  ok(eLocal === null, 'E3 提交成功清本地重内容');
  pend = await store.listPending();
  eq(pend.length, 0, 'E3 待补传清空');

  // ===== F. flush 幂等 / 重入锁 / 不重复上传 =====
  console.log('F. flush 幂等 + 重入锁');
  resetEnv();
  await store.saveDraftLocal({ id: 'lf', category: '住宅', filler: 'u1', basic: { a: '1' },
    photos: [], pendingPhotos: [{ name: 'p1.jpg', dataBase64: 'BB' }],
    updatedAt: 't', status: '草稿', dirty: true, needsSync: true, pendingSubmit: false });
  const beforeUploads = server.state.uploads;
  const pF1 = sync.flush(broker, store);
  const pF2 = sync.flush(broker, store);   // 立即再调 → 应被重入锁挡下
  const [r1, r2] = await Promise.all([pF1, pF2]);
  await tick();
  ok(r2.skipped === true, 'F1 并发第二次 flush 被重入锁跳过');
  eq(r1.synced, 1, 'F1 首次 flush 同步 1 条');
  eq(server.state.uploads - beforeUploads, 1, 'F1 待传照片只上传一次');
  // 再 flush（照片已转 photos，pendingPhotos 空）→ 不再重传
  const u2 = server.state.uploads;
  const draftF = await store.loadDraftLocal('lf');
  eq((draftF.photos || []).length, 1, 'F2 照片已转入 photos');
  eq((draftF.pendingPhotos || []).length, 0, 'F2 pendingPhotos 已空');
  await sync.flush(broker, store);   // lf 已 needsSync=false → listPending 不含它
  eq(server.state.uploads - u2, 0, 'F2 重跑不重传照片');

  // ===== G. 逐因素采集（描述 + 档次下拉）落 content.asset_conditions/subject_levels =====
  console.log('G. 逐因素采集');
  // G0 数据源自检：每类每因素都有档次选项
  let anyEmpty = false;
  Object.keys(FACTORS).forEach((cat) => (FACTORS[cat] || []).forEach((g) =>
    g.items.forEach((it) => { if (!it.levels || !it.levels.length) anyEmpty = true; })));
  ok(!anyEmpty, 'G0 factors.js 每因素都有档次选项');
  ok((FACTORS['办公'] || []).length === 3, 'G0 办公 3 组（区位/实物/权益）');

  resetEnv();
  const fpG = makePage(formCfg);
  fpG.onLoad({});
  const lidG = fpG.data.localId;
  fpG.onCategory({ detail: { value: 1 } });   // 办公
  await tick();
  fpG.onFactors();
  await tick();
  ok(env.spies.navTo.length >= 1, 'G1 表单跳逐因素页');
  const facG = makePage(factorsCfg);
  facG.onLoad({ draftId: lidG });
  await tick();
  eq(facG.data.category, '办公', 'G1 逐因素页读到类别');
  eq(facG.data.groups.length, 3, 'G1 渲染 3 组');
  const f0 = facG.data.groups[0].items[0];   // 区位·重要场所距离
  facG.onLevel({ currentTarget: { dataset: { name: f0.name } }, detail: { value: 0 } });
  facG.onDesc({ currentTarget: { dataset: { name: f0.name } }, detail: { value: '距政府约4公里' } });
  await tick();
  eq(facG.data.levels[f0.name], f0.levels[0], 'G2 选档次落 levels');
  eq(facG.data.descs[f0.name], '距政府约4公里', 'G2 描述落 descs');
  // G4 地图预填自动填入对应区位因素描述（只填空、不覆盖已手填）
  facG.onDesc({ currentTarget: { dataset: { name: '离地铁距离' } }, detail: { value: '手填：紧邻2号线' } });
  await tick();
  facG.onGeo();
  await tick();
  eq(facG.data.geo.metroText, '龙翔桥 约300米', 'G4 地图取到地铁事实');
  eq(facG.data.descs['离地铁距离'], '手填：紧邻2号线', 'G4 已手填的匹配因素不被地图覆盖');
  eq(facG.data.descs['200米内公交线路数'], 'A站、B站', 'G4 空的公交因素被地图填入');
  eq(facG.data.descs['公共服务设施'], '学校、医院', 'G4 空的公共服务设施被地图填入');
  eq(facG.data.descs['停车便利度'], '周边约4个停车场，最近约120米', 'G4 停车便利度←地图停车场');
  eq(facG.data.descs['道路通达度'], '临近：文一路、古墩路', 'G4 道路通达度←就近道路');
  eq(facG.data.descs[f0.name], '距政府约4公里', 'G4 重要场所距离已手填，中心事实不覆盖');
  facG.onDone();
  await tick();
  const gDraft = await store.loadDraftLocal(lidG);
  eq(gDraft.subjectLevels[f0.name], f0.levels[0], 'G2 档次持久到草稿缓存');
  // 回表单 → 提交 → 服务端 content 含逐因素
  fpG.onShow();
  await tick();
  eq(fpG.data.subjectLevels[f0.name], f0.levels[0], 'G3 表单 onShow 拉到档次');
  fpG.onSubmit();
  await tick();
  const gSub = Object.keys(server.state.drafts).map((k) => server.state.drafts[k])
    .find((x) => x.status === '已提交');
  eq(gSub.content.subject_levels[f0.name], f0.levels[0], 'G3 提交后服务端 subject_levels 含档次');
  eq(gSub.content.asset_conditions[f0.name], '距政府约4公里', 'G3 提交后服务端 asset_conditions 含描述');
  eq(gSub.content.asset_conditions['公共服务设施'], '学校、医院', 'G3 地图预填的描述随提交进服务端');

  // ===== H. 入口页：未提交可删 + 已提交按类别分组不可删 =====
  console.log('H. 删除草稿 + 已提交分类展示');
  resetEnv();
  await store.saveDraftLocal({ id: 'ld1', serverId: 'srv-d1', category: '商业', basic: {},
    updatedAt: '2026-07-20T03:00:00Z', status: '草稿', dirty: false, needsSync: false });
  await store.upsertIndexEntry({ id: 'srv-s1', serverId: 'srv-s1', category: '农用',
    status: '已提交', submitted: true, updatedAt: '2026-07-20T02:00:00Z', dirty: false });
  await store.upsertIndexEntry({ id: 'srv-s2', serverId: 'srv-s2', category: '办公',
    status: '已提交', submitted: true, updatedAt: '2026-07-20T01:00:00Z', dirty: false });
  server.state.drafts['srv-d1'] = { category: '商业', status: '草稿', content: {} };
  const ixH = makePage(indexCfg);
  env.offline = true;                 // 跳过服务端对账，纯本地渲染
  ixH.loadMyDrafts();
  await tick();
  eq(ixH.data.drafts.length, 1, 'H1 未提交草稿 1 条（可删区）');
  eq(ixH.data.drafts[0].submitted, false, 'H1 草稿行 submitted=false');
  eq(ixH.data.submittedGroups.length, 2, 'H1 已提交按类别分 2 组');
  const cats = ixH.data.submittedGroups.map((g) => g.category);
  ok(cats.length === 2 && cats.indexOf('农用') >= 0 && cats.indexOf('办公') >= 0,
    'H1 分组类别含农用+办公');
  ok(ixH.data.submittedGroups.every((g) => g.rows.length === 1), 'H1 每组 1 份');
  // 删未提交草稿
  env.offline = false;
  ixH.onDelete({ currentTarget: { dataset: { id: 'ld1' } } });   // confirm 默认点删除
  await tick();
  eq(ixH.data.drafts.length, 0, 'H2 删除后未提交区清空');
  ok(!server.state.drafts['srv-d1'], 'H2 服务端草稿行也被删（best-effort）');
  const hLocal = await store.loadDraftLocal('ld1');
  ok(hLocal === null, 'H2 本地内容已删');
  eq(ixH.data.submittedGroups.length, 2, 'H2 已提交不受影响（仍 2 组、不可删）');

  // ===== G5. 农用类别：离城中心/离高速口/离水源地距离 全被 GPS 填入（对应真机截图那类）=====
  console.log('G5. 农用区位 GPS 预填');
  resetEnv();
  await store.saveDraftLocal({ id: 'lag', category: '农用', filler: 'u1', basic: {},
    updatedAt: 't', status: '草稿', dirty: true, needsSync: false });
  const facAg = makePage(factorsCfg);
  facAg.onLoad({ draftId: 'lag' });
  await tick();
  eq(facAg.data.category, '农用', 'G5 农用类别载入');
  facAg.onGeo();
  await tick();
  eq(facAg.data.descs['离城中心距离'], '西湖区政府 约3.5公里', 'G5 离城中心距离←中心事实');
  eq(facAg.data.descs['离高速口距离'], '留下收费站 约2.1公里', 'G5 离高速口距离←高速事实');
  eq(facAg.data.descs['离水源地距离'], '西溪湿地 约800米', 'G5 离水源地距离←水源事实');
  eq(facAg.data.descs['货车停车便利度'], '周边约4个停车场，最近约120米', 'G5 货车停车便利度←停车场');

  // ===== I. 点「已提交」问卷→从服务端拉内容（修“出空白”bug）=====
  console.log('I. 已提交问卷从服务端拉取（非空白）');
  resetEnv();
  // 模拟提交后状态：索引留轻记录(id=本地lz, serverId=srv-z, 已提交)，本地内容已清，服务端有内容
  await store.upsertIndexEntry({ id: 'lz', serverId: 'srv-z', category: '商业',
    status: '已提交', submitted: true, updatedAt: 't', dirty: false });
  server.state.drafts['srv-z'] = { category: '商业', status: '已提交',
    content: { basic: { client: '李四' }, subject_levels: { 楼层: '中层' },
      asset_conditions: {}, photos: [], gps: null } };
  const pI = makePage(formCfg);
  pI.onLoad({ draftId: 'lz' });   // data-id 是本地 id，本地内容已清
  await tick();
  eq(pI.data.form.basic.client, '李四', 'I 点已提交问卷从服务端拉到内容(非空白)');
  eq(pI.data.form.category, '商业', 'I 类别正确');
  eq(pI.data.subjectLevels['楼层'], '中层', 'I 逐因素档次也从服务端回填');
  eq(pI.data.serverStatus, '已提交', 'I 状态显示已提交');

  // ===== J. 跨设备：服务端有我提交的问卷但本地没有→入口页 listSurveys 拉出来 =====
  console.log('J. 跨设备查看自己提交的问卷');
  resetEnv();
  // 本地无任何草稿；服务端有 u1 在别的设备提交的一份
  server.state.drafts['srv-cd'] = { category: '住宅', status: '已提交', filler: 'u1',
    updated_at: '2026-07-21T09:00:00Z', content: {} };
  // 顺带放一份别人(u2)的，验证不会串到 u1
  server.state.drafts['srv-other'] = { category: '商业', status: '已提交', filler: 'u2',
    updated_at: 't', content: {} };
  const ixJ = makePage(indexCfg);
  ixJ.loadMyDrafts();     // getApp().globalData.filler = 'u1'
  await tick();
  eq(ixJ.data.submittedGroups.length, 1, 'J 拉到服务端「我的」问卷(跨设备)');
  eq(ixJ.data.submittedGroups[0].category, '住宅', 'J 类别正确');
  eq(ixJ.data.submittedGroups[0].rows[0].survey_id, 'srv-cd', 'J 是我提交的那份');
  const jAll = ixJ.data.drafts.concat(ixJ.data.submittedGroups.reduce((a, g) => a.concat(g.rows), []));
  ok(!jAll.some((r) => r.survey_id === 'srv-other'), 'J 不串到别人(u2)的问卷');

  // ===== K. 已定稿/待审核 整份只读（不可改、不进采集/逐因素、提交不动服务端）=====
  console.log('K. 已定稿/待审核只读');
  resetEnv();
  await store.upsertIndexEntry({ id: 'lk', serverId: 'srv-k', category: '住宅',
    status: '已定稿', submitted: true, updatedAt: 't', dirty: false });
  server.state.drafts['srv-k'] = { category: '住宅', status: '已定稿', filler: 'u1',
    content: { basic: { client: '王五' }, subject_levels: {}, asset_conditions: {}, photos: [], gps: null } };
  const pK = makePage(formCfg);
  pK.onLoad({ draftId: 'lk' });   // 本地内容不在 → 从服务端拉，_refreshFromServer 置只读
  await tick();
  ok(pK.data.readonly === true, 'K1 已定稿载入即只读');
  eq(pK.data.serverStatus, '已定稿', 'K1 状态=已定稿');
  eq(pK.data.form.basic.client, '王五', 'K1 只读仍能看到已填内容');
  const kNavBefore = env.spies.navTo.length;
  pK.onCapture();
  pK.onFactors();
  pK.onSubmit();
  await tick();
  eq(env.spies.navTo.length, kNavBefore, 'K2 只读时不进采集/逐因素页');
  eq(server.state.drafts['srv-k'].status, '已定稿', 'K2 只读时点提交不改服务端状态');

  // 待审核同样只读
  resetEnv();
  await store.upsertIndexEntry({ id: 'lk2', serverId: 'srv-k2', category: '办公',
    status: '待审核', submitted: true, updatedAt: 't', dirty: false });
  server.state.drafts['srv-k2'] = { category: '办公', status: '待审核', filler: 'u1',
    content: { basic: {}, subject_levels: {}, asset_conditions: {}, photos: [], gps: null } };
  const pK2 = makePage(formCfg);
  pK2.onLoad({ draftId: 'lk2' });
  await tick();
  ok(pK2.data.readonly === true, 'K3 待审核也整份只读');

  // 已提交仍可改（非只读）
  resetEnv();
  await store.upsertIndexEntry({ id: 'lk3', serverId: 'srv-k3', category: '商业',
    status: '已提交', submitted: true, updatedAt: 't', dirty: false });
  server.state.drafts['srv-k3'] = { category: '商业', status: '已提交', filler: 'u1',
    content: { basic: {}, subject_levels: {}, asset_conditions: {}, photos: [], gps: null } };
  const pK3 = makePage(formCfg);
  pK3.onLoad({ draftId: 'lk3' });
  await tick();
  ok(pK3.data.readonly === false, 'K4 已提交仍可改（非只读）');
  ok(store.isSubmittedStatus('待审核') && store.isSubmittedStatus('已定稿'), 'K5 待审核/已定稿都算已提交类（进已提交分组）');

  // ===== L. 双向同步：带 base 三方合并 + 冲突逐字段解决 =====
  console.log('L. 双向同步（带 base 合并 + 冲突解决）');

  // L1 不同字段并发 → 自动合并，两处都保住；成功后底版推进
  resetEnv();
  server.state.drafts['srv-L'] = { category: '办公', status: '已提交', filler: 'u1', updated_at: 't1',
    content: { basic: { a: '1', b: '1' }, subjects: [], subject_levels: {}, asset_conditions: {}, photos: [], gps: null } };
  await store.saveDraftLocal({ id: 'local-L', serverId: 'srv-L', category: '办公', filler: 'u1',
    basic: { a: 'phone', b: '1' }, subjectLevels: {}, assetConditions: {}, photos: [], gps: null,
    base: { basic: { a: '1', b: '1' }, subjects: [], subject_levels: {}, asset_conditions: {}, photos: [], gps: null },
    updatedAt: 't2', needsSync: true });
  server.state.drafts['srv-L'].content.basic.b = 'server';   // 办公端并发改 b
  const rL = await sync.syncOne(broker, store, 'local-L');
  ok(!rL.conflict, 'L1 不同字段并发 → 无冲突');
  eq(server.state.drafts['srv-L'].content.basic.a, 'phone', 'L1 手机改的 a 保住');
  eq(server.state.drafts['srv-L'].content.basic.b, 'server', 'L1 办公改的 b 保住（未被覆盖）');
  d = await store.loadDraftLocal('local-L');
  eq(d.base.basic.a, 'phone', 'L1 成功后底版推进为已发送内容');

  // L2 同字段双改 → 冲突、未写库
  resetEnv();
  server.state.drafts['srv-M'] = { category: '办公', status: '已提交', filler: 'u1', updated_at: 't1',
    content: { basic: { a: '1' }, subjects: [], subject_levels: {}, asset_conditions: {}, photos: [], gps: null } };
  await store.saveDraftLocal({ id: 'local-M', serverId: 'srv-M', category: '办公', filler: 'u1',
    basic: { a: 'phone' }, subjectLevels: {}, assetConditions: {}, photos: [], gps: null,
    base: { basic: { a: '1' }, subjects: [], subject_levels: {}, asset_conditions: {}, photos: [], gps: null },
    updatedAt: 't2', needsSync: true });
  server.state.drafts['srv-M'].content.basic.a = 'server';
  const rM = await sync.syncOne(broker, store, 'local-M');
  ok(rM.conflict === true, 'L2 同字段双改 → 冲突');
  eq(rM.conflicts[0].field, 'basic.a', 'L2 冲突字段 basic.a');
  eq(server.state.drafts['srv-M'].content.basic.a, 'server', 'L2 冲突未写库（线上仍 server）');

  // L3 resolveConflict 选线上 → 写入所选、本地也更新
  const rM2 = await sync.resolveConflict(broker, store, 'local-M', { 'basic.a': 'server' });
  ok(!rM2.conflict, 'L3 解决后成功');
  eq(server.state.drafts['srv-M'].content.basic.a, 'server', 'L3 选线上 → 写入 server');
  d = await store.loadDraftLocal('local-M');
  eq(d.basic.a, 'server', 'L3 本地内容更到所选值');

  // L4 首个草稿无 base → 整份插入（向后兼容）+ 成功后建立底版
  resetEnv();
  await store.saveDraftLocal({ id: 'local-N', category: '办公', filler: 'u1',
    basic: { a: 'x' }, subjectLevels: {}, assetConditions: {}, photos: [], gps: null,
    updatedAt: 't', needsSync: true });
  const rN = await sync.syncOne(broker, store, 'local-N');
  ok(!rN.conflict && rN.survey_id, 'L4 无 base 首存 → 正常插入');
  d = await store.loadDraftLocal('local-N');
  ok(d.base && d.base.basic.a === 'x', 'L4 首存成功后建立底版');

  // L5 flush 遇冲突：计入 conflicts、不计 synced
  resetEnv();
  server.state.drafts['srv-P'] = { category: '办公', status: '已提交', filler: 'u1', updated_at: 't1',
    content: { basic: { a: '1' }, subjects: [], subject_levels: {}, asset_conditions: {}, photos: [], gps: null } };
  await store.saveDraftLocal({ id: 'local-P', serverId: 'srv-P', category: '办公', filler: 'u1',
    basic: { a: 'phone' }, subjectLevels: {}, assetConditions: {}, photos: [], gps: null,
    base: { basic: { a: '1' }, subjects: [], subject_levels: {}, asset_conditions: {}, photos: [], gps: null },
    updatedAt: 't2', needsSync: true });
  server.state.drafts['srv-P'].content.basic.a = 'server';
  const fl = await sync.flush(broker, store);
  eq(fl.conflicts, 1, 'L5 flush 统计冲突数');
  eq(fl.synced, 0, 'L5 冲突不计入已同步');

  // L6 form.js 从服务端载入即捕获 base
  resetEnv();
  server.state.drafts['srv-Q'] = { category: '办公', status: '已提交', filler: 'u1', updated_at: 't1',
    content: { basic: { a: 'srv' }, subjects: [], subject_levels: {}, asset_conditions: {}, photos: [], gps: null } };
  await store.upsertIndexEntry({ id: 'srv-Q', serverId: 'srv-Q', category: '办公', status: '已提交', submitted: true });
  const pL = makePage(formCfg);
  pL.onLoad({ draftId: 'srv-Q' });
  await tick();
  ok(pL.data.base && pL.data.base.basic.a === 'srv', 'L6 从服务端载入即捕获底版 base');

  // L7 冲突页：选线上确认 → resolveConflict 写入、清 pendingConflict
  require(path.join(__dirname, '../../miniprogram/pages/conflict/conflict.js'));
  const conflictCfg = lastCfg;
  resetEnv();
  server.state.drafts['srv-R'] = { category: '办公', status: '已提交', filler: 'u1', updated_at: 't1',
    content: { basic: { a: 'server' }, subjects: [], subject_levels: {}, asset_conditions: {}, photos: [], gps: null } };
  await store.saveDraftLocal({ id: 'local-R', serverId: 'srv-R', category: '办公', filler: 'u1',
    basic: { a: 'phone' }, subjectLevels: {}, assetConditions: {}, photos: [], gps: null,
    base: { basic: { a: '1' }, subjects: [], subject_levels: {}, asset_conditions: {}, photos: [], gps: null },
    updatedAt: 't2', needsSync: true });
  getApp().globalData.pendingConflict = { draftId: 'local-R',
    conflicts: [{ field: 'basic.a', base: '1', mine: 'phone', theirs: 'server' }] };
  const pConf = makePage(conflictCfg);
  pConf.onLoad();
  await tick();
  eq(pConf.data.items.length, 1, 'L7 冲突页列出 1 条');
  pConf.onPick({ currentTarget: { dataset: { idx: 0, which: 'theirs' } } });   // 选线上
  await tick();
  pConf.onConfirm();
  await tick();
  eq(server.state.drafts['srv-R'].content.basic.a, 'server', 'L7 选线上确认 → 写入 server 值');
  ok(getApp().globalData.pendingConflict === null, 'L7 解决后清空 pendingConflict');

  // ===== M. 选共有人（owners 并集 + 填报人恒在） =====
  console.log('M. 选共有人');

  // M1 新建即以填报人为首个共有人
  resetEnv();
  const pM = makePage(formCfg);
  pM.onLoad({});
  await tick();
  eq(pM.data.owners, ['u1'], 'M1 新建：填报人恒为首个共有人');

  // M2 _addOwners 去重 + filler 恒在 + 存名字
  pM._addOwners([{ userid: 'a', name: '甲' }, { userid: 'u1', name: '我' }, { userid: 'a', name: '甲' }]);
  await tick();
  eq(pM.data.owners, ['u1', 'a'], 'M2 加共有人去重、filler 恒首');
  eq(pM.data.ownerNames.a, '甲', 'M2 存下姓名供展示');

  // M3 暂存把 owners 带上服务端；另一设备并发加人 → 并集累积
  pM.setData({ 'form.category': '办公' });
  pM.onSave();
  await tick();
  const sidM = pM.data.survey_id;
  eq(server.state.drafts[sidM].owners, ['u1', 'a'], 'M3 owners 随保存上服务端');
  await broker.request('saveDraft', { survey_id: sidM, filler: 'u1', category: '办公', updated_at: 't9',
    content: { basic: {}, subjects: [], subject_levels: {}, asset_conditions: {}, photos: [], gps: null },
    owners: ['b'] });
  eq(server.state.drafts[sidM].owners, ['u1', 'a', 'b'], 'M3 并发加共有人并集累积（谁都不丢）');

  // M4 从服务端载入即拿到共有人
  resetEnv();
  await broker.request('saveDraft', { survey_id: 'srv-M4', filler: 'u1', category: '办公', updated_at: 't1',
    content: { basic: {}, subjects: [], subject_levels: {}, asset_conditions: {}, photos: [], gps: null },
    owners: ['u1', 'x'] });
  server.state.drafts['srv-M4'].status = '已提交';
  await store.upsertIndexEntry({ id: 'srv-M4', serverId: 'srv-M4', category: '办公', status: '已提交', submitted: true });
  const pM4 = makePage(formCfg);
  pM4.onLoad({ draftId: 'srv-M4' });
  await tick();
  ok(pM4.data.owners.indexOf('x') >= 0 && pM4.data.owners.indexOf('u1') >= 0, 'M4 载入服务端共有人');

  // M5 移除非填报人；填报人不可删
  const pM5 = makePage(formCfg);
  pM5.onLoad({});
  await tick();
  pM5._addOwners([{ userid: 'a', name: '甲' }]);
  await tick();
  pM5.onRemoveOwner({ currentTarget: { dataset: { uid: 'a' } } });
  await tick();
  eq(pM5.data.owners, ['u1'], 'M5 移除共有人 a');
  pM5.onRemoveOwner({ currentTarget: { dataset: { uid: 'u1' } } });   // 尝试删填报人
  await tick();
  eq(pM5.data.owners, ['u1'], 'M5 填报人不可删');

  console.log(`\n结果：${PASS} 通过，${FAIL} 失败`);
  process.exit(FAIL ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(2); });
