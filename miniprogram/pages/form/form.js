const broker = require('../../utils/broker');
const app = getApp();

const FIELDS = [
  { key: 'project_name', label: '项目名称' }, { key: 'client', label: '委托人' },
  { key: 'client_address', label: '委托人地址' }, { key: 'legal_rep', label: '法定代表人' },
  { key: 'purpose', label: '估价目的' }, { key: 'survey_date', label: '实地查勘日期' },
  { key: 'value_date', label: '价值时点' }, { key: 'materials', label: '提供资料' },
  { key: 'certificate_status', label: '权属证书情况' }, { key: 'owner', label: '权利人' },
  { key: 'address', label: '坐落' }, { key: 'usage', label: '设定出租用途' },
  { key: 'scale', label: '规模' }, { key: 'scope', label: '估价范围' },
  { key: 'current_status', label: '利用现状' }, { key: 'surveyor', label: '查勘人' },
  { key: 'report_no', label: '报告编号(可空)' }, { key: 'issue_date', label: '报告出具日期' },
  { key: 'work_period', label: '估价作业期' },
];
const CATEGORIES = ['农用', '办公', '商业', '住宅', '工业', '停车场用地', '建设用地'];

Page({
  data: {
    fields: FIELDS, categories: CATEGORIES, catIndex: 0,
    form: { category: '', basic: {} },
    survey_id: '', gps: null, geo: {}, msg: '',
  },

  onLoad(q) {
    if (q && q.draftId) this.resume(q.draftId);
  },

  resume(id) {
    broker.request('loadDraft', { survey_id: id }).then((d) => {
      const c = d.content || {};
      this.setData({
        survey_id: id,
        form: { category: d.category || '', basic: c.basic || {} },
        gps: c.gps || null,
        catIndex: Math.max(0, CATEGORIES.indexOf(d.category)),
      });
    }).catch((e) => this.setData({ msg: '载入草稿失败：' + e.detail }));
  },

  onCategory(e) {
    const cat = CATEGORIES[e.detail.value];
    this.setData({ catIndex: e.detail.value, 'form.category': cat });
  },
  onField(e) {
    this.setData({ ['form.basic.' + e.currentTarget.dataset.key]: e.detail.value });
  },

  onGeo() {
    dd.getLocation({
      success: (loc) => {
        this.setData({ gps: { lat: loc.latitude, lng: loc.longitude } });
        broker.request('prefillGeo', { lng: loc.longitude, lat: loc.latitude }).then((f) => {
          const metro = f.nearest_metro;
          this.setData({ geo: {
            address: f.address,
            bus_stops: (f.bus_stops || []).join('、') || '（无）',
            facilities: (f.facilities || []).slice(0, 6).join('、'),
            metroText: metro ? (metro.name + ' 约' + metro.distance_m + '米') : '（无）',
          }});
        }).catch((e) => this.setData({ msg: '地图预填失败：' + e.detail }));
      },
      fail: (e) => this.setData({ msg: '取定位失败：' + ((e && e.errorMessage) || '') }),
    });
  },

  _content() {
    return {
      basic: this.data.form.basic,
      gps: this.data.gps,
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
    broker.request('saveDraft', this._payload()).then((r) => {
      this.rememberLocal(r.survey_id);
      this.setData({ survey_id: r.survey_id, msg: '已暂存：' + r.survey_id });
    }).catch((e) => this.setData({ msg: '暂存失败：' + e.detail }));
  },

  onSubmit() {
    if (!this.data.form.category) { this.setData({ msg: '请先选类别' }); return; }
    // 先存（拿到/更新 survey_id）再提交
    broker.request('saveDraft', this._payload()).then((r) => {
      this.rememberLocal(r.survey_id);
      this.setData({ survey_id: r.survey_id });
      return broker.request('submit', { survey_id: r.survey_id });
    }).then(() => {
      this.setData({ msg: '已提交，办公端可拉取。' });
    }).catch((e) => this.setData({ msg: '提交失败：' + e.detail }));
  },

  rememberLocal(id) {
    dd.getStorage({ key: 'myDrafts', success: (res) => {
      const ids = res.data || [];
      if (ids.indexOf(id) < 0) ids.push(id);
      dd.setStorage({ key: 'myDrafts', data: ids });
    }, fail: () => dd.setStorage({ key: 'myDrafts', data: [id] }) });
  },
});
