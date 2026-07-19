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

let PASS = 0, FAIL = 0;
function ok(cond, msg) { if (cond) { PASS++; } else { FAIL++; console.log('  ✗ FAIL: ' + msg); } }
function eq(a, b, msg) { ok(JSON.stringify(a) === JSON.stringify(b), msg + ` (got ${JSON.stringify(a)}, want ${JSON.stringify(b)})`); }

// ---- server 打桩 ----
function makeServer() {
  const state = { seq: 0, drafts: {} };
  function route(req) {
    const a = req.action, p = req.payload || {};
    if (a === 'saveDraft') {
      const sid = p.survey_id || ('srv-' + (++state.seq));
      state.drafts[sid] = { category: p.category, content: clone(p.content),
        status: (state.drafts[sid] && state.drafts[sid].status) || '草稿', updated_at: p.updated_at };
      return { survey_id: sid };
    }
    if (a === 'submit') { if (state.drafts[p.survey_id]) state.drafts[p.survey_id].status = '已提交'; return { ok: true }; }
    if (a === 'loadDraft') {
      const d = state.drafts[p.survey_id] || {};
      return { category: d.category || '', content: d.content || {}, status: d.status || '', updated_at: d.updated_at || '' };
    }
    if (a === 'prefillGeo') return { address: '杭州市西湖区某路', bus_stops: ['A站', 'B站'],
      facilities: ['学校', '医院'], nearest_metro: { name: '龙翔桥', distance_m: 300 } };
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
global.getApp = () => ({ globalData: { filler: 'u1', fillerName: '薛焱', BASE_URL: '' } });
global.getCurrentPages = () => [{}];               // length 1 → 提交后走 reLaunch
global.setTimeout = (fn) => { fn(); return 0; };    // 自动退出回调同步执行，便于断言

function applySetData(data, patch) {
  for (const k of Object.keys(patch)) {
    if (k.indexOf('.') >= 0) {
      const parts = k.split('.'); let o = data;
      for (let i = 0; i < parts.length - 1; i++) {
        if (o[parts[i]] == null || typeof o[parts[i]] !== 'object') o[parts[i]] = {};
        o = o[parts[i]];
      }
      o[parts[parts.length - 1]] = patch[k];
    } else data[k] = patch[k];
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
require(path.join(__dirname, '../../miniprogram/utils/broker.js'));
require(path.join(__dirname, '../../miniprogram/pages/form/form.js'));
const formCfg = lastCfg;
require(path.join(__dirname, '../../miniprogram/pages/index/index.js'));
const indexCfg = lastCfg;

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
  server.state.drafts['srv-x'] = { category: '农用', status: '已提交', content: {}, updated_at: '2026-07-20T02:00:00Z' };
  const ix = makePage(indexCfg);
  ix.onShow();
  await tick();
  eq(ix.data.drafts.length, 1, 'C1 入口列出一条');
  eq(ix.data.drafts[0].status, '已提交', 'C1 联网对账把状态刷成已提交');

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

  console.log(`\n结果：${PASS} 通过，${FAIL} 失败`);
  process.exit(FAIL ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(2); });
