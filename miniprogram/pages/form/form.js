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
    msg: '',
    serverStatus: '',       // 载入/存过后的服务端状态：草稿 / 已提交
    dirty: false,           // 本地有改动、尚未成功同步（驱动「未同步」徽标）
    offline: false,         // 上一次网络操作失败（数据已在本机）
    needsSync: false,       // 点过暂存/提交但未成功——离线补传只认这个（防把没保存的草稿也推上去）
    pendingSubmit: false,   // 意图是提交而非只暂存——离线补传据此 submit
  },

  onLoad(q) {
    if (q && q.draftId) this.resume(q.draftId);
    else this.setData({ localId: store.newLocalId() });   // 新建即建本地 id
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

  // 续填：先本地内容秒回填，再联网对账
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
          catIndex: Math.max(0, CATEGORIES.indexOf(d.category)),
          fields: fieldsFor(d.category || ''),
          serverStatus: d.status || '', dirty: !!d.dirty,
        });
      } else {
        this.setData({ localId: isLocal ? id : store.newLocalId(),
          survey_id: isLocal ? '' : id });
      }
      const sid = (d && d.serverId) || (isLocal ? '' : id);
      if (sid) this._refreshFromServer(sid);
    });
  },

  // 联网用服务端版本对账（本地有未同步改动时不覆盖，护住现场输入）
  _refreshFromServer(sid) {
    broker.request('loadDraft', { survey_id: sid }).then((d) => {
      if (this.data.dirty) { this.setData({ offline: false }); return; }
      const c = d.content || {};
      const draft = {
        id: this.data.localId || sid, serverId: sid,
        filler: app.globalData.filler || '',
        category: d.category || '', basic: c.basic || {}, gps: c.gps || null,
        geo: this.data.geo || {}, photos: c.photos || [],
        pendingPhotos: this.data.pendingPhotos || [],
        subjectLevels: c.subject_levels || {}, assetConditions: c.asset_conditions || {},
        updatedAt: d.updated_at || '', status: d.status || '', dirty: false,
      };
      store.saveDraftLocal(draft);
      this.setData({
        survey_id: sid, form: { category: draft.category, basic: draft.basic },
        gps: draft.gps, photos: draft.photos,
        subjectLevels: draft.subjectLevels, assetConditions: draft.assetConditions,
        catIndex: Math.max(0, CATEGORIES.indexOf(draft.category)),
        fields: fieldsFor(draft.category || ''),
        serverStatus: draft.status, dirty: false, offline: false,
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
      updatedAt: new Date().toISOString(),
      status: this.data.serverStatus || '草稿',
      dirty: true, needsSync: this.data.needsSync, pendingSubmit: this.data.pendingSubmit,
    }, extra || {});
  },

  // 任一改动即本地存盘（改动即存，不丢）
  _autosave() {
    this.setData({ dirty: true });
    store.saveDraftLocal(this._draftObj({ dirty: true }));
  },

  onCategory(e) {
    const cat = CATEGORIES[e.detail.value];
    this.setData({ catIndex: e.detail.value, 'form.category': cat, fields: fieldsFor(cat) });
    this._autosave();
  },
  onField(e) {
    this.setData({ ['form.basic.' + e.currentTarget.dataset.key]: e.detail.value });
    this._autosave();
  },

  // 进现场采集页（拍照 + 地图预填）；先把当前基本字段落盘，采集页据同一 localId 读写。
  onCapture() {
    const id = this.data.localId || store.newLocalId();
    if (!this.data.localId) this.setData({ localId: id });
    store.saveDraftLocal(this._draftObj({ dirty: true }));
    dd.navigateTo({ url: '/pages/capture/capture?draftId=' + id });
  },

  // 进逐因素页（按类别填描述+档次）；须先选类别。
  onFactors() {
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
      updated_at: new Date().toISOString(),
      content: this._content(),
    };
  },

  onSave() {
    if (!this.data.form.category) { this.setData({ msg: '请先选类别' }); return; }
    // needsSync 置真并落本机（保证不丢；离线时后台会据此补传），再走统一 syncOne。
    this.setData({ needsSync: true, pendingSubmit: false });
    store.saveDraftLocal(this._draftObj({ dirty: true }));
    sync.syncOne(broker, store, this.data.localId).then((r) => {
      if (r.skipped) return;
      this.rememberLegacy(r.survey_id);
      this.setData({ survey_id: r.survey_id, serverStatus: '草稿', dirty: false,
        needsSync: false, offline: false, photos: r.photos || this.data.photos,
        msg: '已暂存：' + r.survey_id });
    }).catch((e) => this.setData({ offline: true,
      msg: '未同步（已存本机，联网后自动补传）：' + ((e && e.detail) || '网络错误') }));
  },

  onSubmit() {
    if (!this.data.form.category) { this.setData({ msg: '请先选类别' }); return; }
    this.setData({ needsSync: true, pendingSubmit: true });   // 提交意图黏住，离线补传据此 submit
    store.saveDraftLocal(this._draftObj({ dirty: true }));
    sync.syncOne(broker, store, this.data.localId).then((r) => {
      if (r.skipped) return;
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
