const broker = require('../../utils/broker');
const store = require('../../utils/store');
const sync = require('../../utils/sync');
const app = getApp();

// 标签与实勘表 xlsx 左列逐字一致（tools/gen_survey_factors 同源实测）。
const FIELDS = [
  { key: 'project_name', label: '项目名称' }, { key: 'client', label: '委托人' },
  { key: 'client_address', label: '住址' }, { key: 'legal_rep', label: '法定代表人或负责人' },
  { key: 'purpose', label: '估价目的' }, { key: 'survey_date', label: '实地勘查日期' },
  { key: 'value_date', label: '价值时点' }, { key: 'materials', label: '委托人提供的材料' },
  { key: 'certificate_status', label: '是否取得产权证书' }, { key: 'owner', label: '权利人' },
  { key: 'address', label: '地址' }, { key: 'usage', label: '设定出租用途' },
  { key: 'scale', label: '估价对象规模' }, { key: 'scope', label: '估价范围' },
  { key: 'current_status', label: '现使用状况' }, { key: 'surveyor', label: '现场查勘记录人员' },
  { key: 'report_no', label: '评估报告编号' }, { key: 'issue_date', label: '估价报告出具日期' },
  { key: 'work_period', label: '估价作业期' },
];
// 逐类别标签微差：实测「办公/商业」的规模列不带「估价对象」前缀。
// （工业/建设用地 xlsx 的 F3/F4 标签互换是已知 Excel 笔误，代码按单元格位置取值，
//  故 issue_date/work_period 统一用规范标签，不照抄那处笔误。）
const LABEL_OVERRIDES = { scale: { 办公: '规模', 商业: '规模' } };
function fieldsFor(category) {
  return FIELDS.map((f) => {
    const ov = LABEL_OVERRIDES[f.key];
    return ov && ov[category] ? { key: f.key, label: ov[category] } : f;
  });
}
const CATEGORIES = ['农用', '办公', '商业', '住宅', '工业', '停车场用地', '建设用地'];

Page({
  data: {
    fields: FIELDS, categories: CATEGORIES, catIndex: 0,
    form: { category: '', basic: {} },
    localId: '', survey_id: '', gps: null, geo: {},
    photos: [], pendingPhotos: [],       // 采集页拥有；表单只随草稿带上传/持久
    subjectLevels: {}, assetConditions: {},  // 逐因素页拥有：档次 / 描述
    base: null,             // 双向同步：上次同服务端一致的内容底版，保存时带上让 broker 三方合并
    owners: [],             // 共有人 userid 列表（填报人恒在、不可删）；办公端按它判可见/编辑
    ownerNames: {},         // userid → 姓名（仅展示；随草稿存，避免每次重查通讯录）
    filler: '',             // 当前登录人 userid（=填报人；用于「不可删」判断）
    msg: '',
    serverStatus: '',       // 载入/存过后的服务端状态：草稿 / 已提交 / 待审核 / 已定稿
    readonly: false,        // 已进入审核流程（待审核/已定稿）→ 整份只读，不可再改
    dirty: false,           // 本地有改动、尚未成功同步（驱动「未同步」徽标）
    offline: false,         // 上一次网络操作失败（数据已在本机）
    needsSync: false,       // 点过暂存/提交但未成功——离线补传只认这个（防把没保存的草稿也推上去）
    pendingSubmit: false,   // 意图是提交而非只暂存——离线补传据此 submit
  },

  onLoad(q) {
    const me = app.globalData.filler || '';
    this.setData({ filler: me });
    if (q && q.draftId) { this.resume(q.draftId); return; }
    // 新建：本地 id + 填报人恒为首个共有人
    const names = {};
    if (me) names[me] = app.globalData.fillerName || '我';
    this.setData({ localId: store.newLocalId(), owners: me ? [me] : [], ownerNames: names });
  },

  // 填报人恒在共有人内且排首位（不可删）。
  _ensureFiller(owners) {
    const me = app.globalData.filler || '';
    const out = me ? [me] : [];
    (owners || []).forEach((u) => { if (u && out.indexOf(u) < 0) out.push(u); });
    return out;
  },

  // 并入选中的共有人（去重、filler 恒在），存名字供展示，落盘。
  _addOwners(picked) {
    const owners = this.data.owners.slice();
    const names = store.assign(this.data.ownerNames, {});
    (picked || []).forEach((p) => {
      const uid = p && (p.userid || p.userId || p.emplId || p.id);
      if (!uid) return;
      if (owners.indexOf(uid) < 0) owners.push(uid);
      names[uid] = p.name || p.userName || uid;
    });
    this.setData({ owners: this._ensureFiller(owners), ownerNames: names });
    this._autosave();
  },

  // 从钉钉通讯录选共有人。**真机验通（2026-08-15）**：选人面板正常弹出、选中人进共有人列表。
  //  刻意保留「取三候选里第一个可用 API + 多字段兜底映射」的写法——它跨基础库/端稳健，
  //  真机实测即经此路径通过；不同环境哪个 API 可用会变，故不写死某一个。
  //  （回执字段兜底见 _addOwners：userid/userId/emplId/id + name/userName。）
  onPickOwners() {
    if (this._lockedGuard()) return;
    const self = this;
    const api = dd.chooseInteriorContacts || dd.complexChoose || dd.chooseContact;
    if (typeof api !== 'function') { this.setData({ msg: '当前环境不支持选人，请在钉钉内打开' }); return; }
    api({
      multiple: true, limitTips: '最多选 20 人', maxUsers: 20,
      success(res) {
        const list = (res && (res.contacts || res.users || res.result)) || [];
        self._addOwners(list);
      },
      fail() { self.setData({ msg: '选人已取消或失败' }); },
    });
  },

  onRemoveOwner(e) {
    if (this._lockedGuard()) return;
    const uid = e.currentTarget.dataset.uid;
    if (!uid || uid === (app.globalData.filler || '')) return;   // 填报人不可删
    this.setData({ owners: this.data.owners.filter((u) => u !== uid) });
    this._autosave();
  },

  // 回到表单（含从采集页返回）：拉采集页写的照片/定位；顺带尝试离线补传。
  onShow() {
    const id = this.data.localId;
    if (id) store.loadDraftLocal(id).then((d) => {
      if (d) this.setData({ photos: d.photos || [], pendingPhotos: d.pendingPhotos || [],
        gps: d.gps || null, geo: d.geo || {},
        subjectLevels: d.subjectLevels || {}, assetConditions: d.assetConditions || {} });
    });
    sync.flush(broker, store);
  },

  // 续填/查看：先本地内容秒回填；本地没有(如已提交清过缓存)则从索引取 serverId 回服务端拉。
  resume(id) {
    const isLocal = String(id).indexOf('local-') === 0;
    store.loadDraftLocal(id).then((d) => {
      if (d) {
        this.setData({
          localId: d.id || id,
          survey_id: d.serverId || (isLocal ? '' : id),
          form: { category: d.category || '', basic: d.basic || {} },
          gps: d.gps || null, geo: d.geo || {},
          photos: d.photos || [], pendingPhotos: d.pendingPhotos || [],
          subjectLevels: d.subjectLevels || {}, assetConditions: d.assetConditions || {},
          base: d.base || null,
          owners: this._ensureFiller(d.owners || []), ownerNames: d.ownerNames || {},
          catIndex: Math.max(0, CATEGORIES.indexOf(d.category)),
          fields: fieldsFor(d.category || ''),
          serverStatus: d.status || '', dirty: !!d.dirty,
          readonly: store.isReadonlyStatus(d.status || ''),
        });
        const sid = d.serverId || (isLocal ? '' : id);
        if (sid) this._refreshFromServer(sid);
        return;
      }
      // 本地内容不在：从索引找该条的 serverId，回服务端拉（修「点已提交问卷出空白」）
      store.readIndex().then((list) => {
        let sid = isLocal ? '' : id;
        for (let i = 0; i < list.length; i++) {
          if (list[i].id === id) { sid = list[i].serverId || sid; break; }
        }
        this.setData({ localId: id, survey_id: sid });
        if (sid) this._refreshFromServer(sid);
        else this.setData({ msg: '未找到该问卷内容（可能尚未同步到服务端）' });
      });
    });
  },

  // 联网用服务端版本对账（本地有未同步改动时不覆盖，护住现场输入）
  _refreshFromServer(sid) {
    broker.request('loadDraft', { survey_id: sid }).then((d) => {
      const ro = store.isReadonlyStatus(d.status || '');
      // 服务端已进入审核/定稿即锁定：即便本地有 dirty（不覆盖其内容），也把表单置只读。
      if (this.data.dirty) { this.setData({ offline: false, readonly: ro }); return; }
      const c = d.content || {};
      // 服务端内容即三方合并的底版：整份存下（六键），供保存回问卷时和线上比对。
      const base = {
        basic: c.basic || {}, gps: c.gps || null, subjects: c.subjects || [],
        subject_levels: c.subject_levels || {}, asset_conditions: c.asset_conditions || {},
        photos: c.photos || [],
      };
      // 服务端返回共有人（userid，无名字）→ 已知名字沿用、未知用 userid 兜底展示。
      const owners = this._ensureFiller(d.owners || []);
      const ownerNames = store.assign(this.data.ownerNames || {}, {});
      owners.forEach((u) => { if (!ownerNames[u]) ownerNames[u] = u; });
      const draft = {
        id: this.data.localId || sid, serverId: sid,
        filler: app.globalData.filler || '',
        category: d.category || '', basic: c.basic || {}, gps: c.gps || null,
        geo: this.data.geo || {}, photos: c.photos || [],
        pendingPhotos: this.data.pendingPhotos || [],
        subjectLevels: c.subject_levels || {}, assetConditions: c.asset_conditions || {},
        base: base, owners: owners, ownerNames: ownerNames,
        updatedAt: d.updated_at || '', status: d.status || '', dirty: false,
      };
      store.saveDraftLocal(draft);
      this.setData({
        survey_id: sid, form: { category: draft.category, basic: draft.basic },
        gps: draft.gps, photos: draft.photos,
        subjectLevels: draft.subjectLevels, assetConditions: draft.assetConditions,
        base: base, owners: owners, ownerNames: ownerNames,
        catIndex: Math.max(0, CATEGORIES.indexOf(draft.category)),
        fields: fieldsFor(draft.category || ''),
        serverStatus: draft.status, dirty: false, offline: false,
        readonly: ro,
      });
    }).catch(() => this.setData({ offline: true }));
  },

  _draftObj(extra) {
    return store.assign({
      id: this.data.localId, serverId: this.data.survey_id || '',
      filler: app.globalData.filler || '',
      category: this.data.form.category, basic: this.data.form.basic,
      gps: this.data.gps, geo: this.data.geo,
      photos: this.data.photos || [], pendingPhotos: this.data.pendingPhotos || [],
      subjectLevels: this.data.subjectLevels || {}, assetConditions: this.data.assetConditions || {},
      base: this.data.base || null,   // 底版随草稿持久化（否则自动存盘会把它冲掉）
      owners: this._ensureFiller(this.data.owners), ownerNames: this.data.ownerNames || {},
      updatedAt: store.nowStamp(),
      status: this.data.serverStatus || '草稿',
      dirty: true, needsSync: this.data.needsSync, pendingSubmit: this.data.pendingSubmit,
    }, extra || {});
  },

  // 任一改动即本地存盘（改动即存，不丢）
  _autosave() {
    this.setData({ dirty: true });
    store.saveDraftLocal(this._draftObj({ dirty: true }));
  },

  // 只读（待审核/已定稿）时提示不可改；用于 onSave/onSubmit/onCapture/onFactors 的统一挡口。
  _lockedGuard() {
    if (!this.data.readonly) return false;
    this.setData({ msg: this.data.serverStatus === '已定稿' ? '已定稿，不可修改' : '审核中，不可修改' });
    return true;
  },

  onCategory(e) {
    if (this.data.readonly) return;   // 只读时忽略（UI 上 picker 也已 disabled）
    const cat = CATEGORIES[e.detail.value];
    this.setData({ catIndex: e.detail.value, 'form.category': cat, fields: fieldsFor(cat) });
    this._autosave();
  },
  onField(e) {
    if (this.data.readonly) return;   // 只读时忽略（UI 上 input 也已 disabled）
    this.setData({ ['form.basic.' + e.currentTarget.dataset.key]: e.detail.value });
    this._autosave();
  },

  // 进现场采集页（拍照 + 地图预填）；先把当前基本字段落盘，采集页据同一 localId 读写。
  onCapture() {
    if (this._lockedGuard()) return;   // 只读：不让进采集页
    const id = this.data.localId || store.newLocalId();
    if (!this.data.localId) this.setData({ localId: id });
    store.saveDraftLocal(this._draftObj({ dirty: true }));
    dd.navigateTo({ url: '/pages/capture/capture?draftId=' + id });
  },

  // 进逐因素页（按类别填描述+档次）；须先选类别。
  onFactors() {
    if (this._lockedGuard()) return;   // 只读：不让进逐因素页
    if (!this.data.form.category) { this.setData({ msg: '请先选类别再填逐因素' }); return; }
    const id = this.data.localId || store.newLocalId();
    if (!this.data.localId) this.setData({ localId: id });
    store.saveDraftLocal(this._draftObj({ dirty: true }));
    dd.navigateTo({ url: '/pages/factors/factors?draftId=' + id });
  },

  _content() {
    return {
      basic: this.data.form.basic, gps: this.data.gps,
      subjects: [],
      subject_levels: this.data.subjectLevels || {},
      asset_conditions: this.data.assetConditions || {},
      photos: this.data.photos || [],
    };
  },
  _payload() {
    return {
      survey_id: this.data.survey_id || undefined,
      filler: app.globalData.filler || '',
      category: this.data.form.category,
      updated_at: store.nowStamp(),
      content: this._content(),
    };
  },

  onSave() {
    if (this._lockedGuard()) return;
    if (!this.data.form.category) { this.setData({ msg: '请先选类别' }); return; }
    // needsSync 置真并落本机（保证不丢；离线时后台会据此补传），再走统一 syncOne。
    this.setData({ needsSync: true, pendingSubmit: false });
    store.saveDraftLocal(this._draftObj({ dirty: true }));
    sync.syncOne(broker, store, this.data.localId).then((r) => {
      if (r.skipped) return;
      if (r.conflict) { this._goResolveConflict(r); return; }
      this.rememberLegacy(r.survey_id);
      this.setData({ survey_id: r.survey_id, serverStatus: '草稿', dirty: false,
        needsSync: false, offline: false, photos: r.photos || this.data.photos,
        base: r.base || this.data.base, msg: '已暂存：' + r.survey_id });
    }).catch((e) => this.setData({ offline: true,
      msg: '未同步（已存本机，联网后自动补传）：' + ((e && e.detail) || '网络错误') }));
  },

  // 保存遇同字段冲突：把冲突暂存到全局，跳冲突页逐字段选（解决后回来带 resolutions 重发）。
  _goResolveConflict(r) {
    app.globalData.pendingConflict = { draftId: this.data.localId, conflicts: r.conflicts || [] };
    this.setData({ dirty: true, needsSync: true, offline: false, msg: '问卷有冲突，请逐项选择保留哪个' });
    dd.navigateTo({ url: '/pages/conflict/conflict?draftId=' + this.data.localId });
  },

  onSubmit() {
    if (this._lockedGuard()) return;
    if (!this.data.form.category) { this.setData({ msg: '请先选类别' }); return; }
    this.setData({ needsSync: true, pendingSubmit: true });   // 提交意图黏住，离线补传据此 submit
    store.saveDraftLocal(this._draftObj({ dirty: true }));
    sync.syncOne(broker, store, this.data.localId).then((r) => {
      if (r.skipped) return;
      if (r.conflict) { this._goResolveConflict(r); return; }
      this.rememberLegacy(r.survey_id);
      this.setData({ survey_id: r.survey_id, serverStatus: '已提交', dirty: false,
        needsSync: false, pendingSubmit: false, offline: false, msg: '已提交，办公端可拉取。' });
      dd.showToast({ content: '已提交同步', type: 'success', duration: 1500 });
      // 稍候自动退回入口页（入口页 onShow 刷新列表，显示「已提交」）
      setTimeout(() => {
        const pages = (typeof getCurrentPages === 'function') ? getCurrentPages() : [];
        if (pages.length > 1) dd.navigateBack();
        else dd.reLaunch({ url: '/pages/index/index' });
      }, 1200);
    }).catch((e) => this.setData({ offline: true,
      msg: '提交失败（已存本机，联网后自动补传并提交）：' + ((e && e.detail) || '网络错误') }));
  },

  // v1 兼容：继续维护 myDrafts（回滚到 v1 代码仍能列出）
  rememberLegacy(id) {
    dd.getStorage({ key: 'myDrafts', success: (res) => {
      const ids = res.data || [];
      if (ids.indexOf(id) < 0) ids.push(id);
      dd.setStorage({ key: 'myDrafts', data: ids });
    }, fail: () => dd.setStorage({ key: 'myDrafts', data: [id] }) });
  },
});
