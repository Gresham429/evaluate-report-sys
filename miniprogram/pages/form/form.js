const broker = require('../../utils/broker');
const store = require('../../utils/store');
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
    localId: '', survey_id: '', gps: null, geo: {}, msg: '',
    serverStatus: '',   // 载入/存过后的服务端状态：草稿 / 已提交
    dirty: false,       // 本地有改动、尚未成功同步
    offline: false,     // 上一次网络操作失败（数据已在本机）
  },

  onLoad(q) {
    if (q && q.draftId) this.resume(q.draftId);
    else this.setData({ localId: store.newLocalId() });   // 新建即建本地 id
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
        category: d.category || '', basic: c.basic || {}, gps: c.gps || null,
        geo: this.data.geo || {}, updatedAt: d.updated_at || '',
        status: d.status || '', dirty: false,
      };
      store.saveDraftLocal(draft);
      this.setData({
        survey_id: sid, form: { category: draft.category, basic: draft.basic },
        gps: draft.gps, catIndex: Math.max(0, CATEGORIES.indexOf(draft.category)),
        fields: fieldsFor(draft.category || ''),
        serverStatus: draft.status, dirty: false, offline: false,
      });
    }).catch(() => this.setData({ offline: true }));
  },

  _draftObj(extra) {
    return store.assign({
      id: this.data.localId, serverId: this.data.survey_id || '',
      category: this.data.form.category, basic: this.data.form.basic,
      gps: this.data.gps, geo: this.data.geo,
      updatedAt: new Date().toISOString(),
      status: this.data.serverStatus || '草稿', dirty: true,
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

  onGeo() {
    dd.getLocation({
      success: (loc) => {
        this.setData({ gps: { lat: loc.latitude, lng: loc.longitude } });
        this._autosave();
        broker.request('prefillGeo', { lng: loc.longitude, lat: loc.latitude }).then((f) => {
          const metro = f.nearest_metro;
          this.setData({ geo: {
            address: f.address,
            bus_stops: (f.bus_stops || []).join('、') || '（无）',
            facilities: (f.facilities || []).slice(0, 6).join('、'),
            metroText: metro ? (metro.name + ' 约' + metro.distance_m + '米') : '（无）',
          }});
          this._autosave();
        }).catch((e) => this.setData({ msg: '地图预填失败：' + e.detail, offline: true }));
      },
      fail: (e) => this.setData({ msg: '取定位失败：' + ((e && e.errorMessage) || '') }),
    });
  },

  _content() {
    return {
      basic: this.data.form.basic, gps: this.data.gps,
      subjects: [], subject_levels: {}, asset_conditions: {}, photos: [],
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
    store.saveDraftLocal(this._draftObj({ dirty: true }));   // 先落本机，保证不丢
    broker.request('saveDraft', this._payload()).then((r) => {
      this.rememberLegacy(r.survey_id);
      store.attachServerId(this.data.localId, r.survey_id);
      store.saveDraftLocal(this._draftObj({ serverId: r.survey_id, status: '草稿', dirty: false }));
      this.setData({ survey_id: r.survey_id, serverStatus: '草稿', dirty: false,
        offline: false, msg: '已暂存：' + r.survey_id });
    }).catch((e) => this.setData({ offline: true,
      msg: '未同步（已存本机，联网后重试）：' + ((e && e.detail) || '网络错误') }));
  },

  onSubmit() {
    if (!this.data.form.category) { this.setData({ msg: '请先选类别' }); return; }
    store.saveDraftLocal(this._draftObj({ dirty: true }));   // 先落本机
    broker.request('saveDraft', this._payload()).then((r) => {
      this.rememberLegacy(r.survey_id);
      store.attachServerId(this.data.localId, r.survey_id);
      this.setData({ survey_id: r.survey_id });
      return broker.request('submit', { survey_id: r.survey_id });
    }).then(() => {
      store.clearDraftContent(this.data.localId);   // 提交成功清重内容，索引留「已提交」
      this.setData({ serverStatus: '已提交', dirty: false, offline: false,
        msg: '已提交，办公端可拉取。' });
      dd.showToast({ content: '已提交同步', type: 'success', duration: 1500 });
      // 稍候自动退回入口页（入口页 onShow 刷新列表，显示「已提交」）
      setTimeout(() => {
        const pages = (typeof getCurrentPages === 'function') ? getCurrentPages() : [];
        if (pages.length > 1) dd.navigateBack();
        else dd.reLaunch({ url: '/pages/index/index' });
      }, 1200);
    }).catch((e) => this.setData({ offline: true,
      msg: '提交失败（已存本机，联网后重试）：' + ((e && e.detail) || '网络错误') }));
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
