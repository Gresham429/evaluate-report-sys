const store = require('../../utils/store');
const FACTORS = require('../../factors');

// 逐因素采集：按类别渲染实勘表左列各因素，每项「描述(自由文字)+档次(下拉，取自基础表)」。
// 描述→content.asset_conditions[因素名]；档次→content.subject_levels[因素名]（键对齐办公端）。
Page({
  data: {
    localId: '', category: '',
    groups: [],          // [{section, items:[{name, levels:[...]}]}]
    descs: {}, levels: {},   // 因素名 → 描述 / 档次
  },

  onLoad(q) {
    const id = (q && q.draftId) || '';
    this.setData({ localId: id });
    if (id) store.loadDraftLocal(id).then((d) => {
      const cat = (d && d.category) || (q && q.category) || '';
      this.setData({
        category: cat, groups: FACTORS[cat] || [],
        descs: (d && d.assetConditions) || {}, levels: (d && d.subjectLevels) || {},
      });
    });
  },

  onDesc(e) {
    const name = e.currentTarget.dataset.name;
    this.setData({ ['descs.' + name]: e.detail.value });
    this._persist();
  },
  onLevel(e) {
    const name = e.currentTarget.dataset.name;
    const factor = this._factor(name);
    const level = factor ? (factor.levels[e.detail.value] || '') : '';
    this.setData({ ['levels.' + name]: level });
    this._persist();
  },
  _factor(name) {
    for (let i = 0; i < this.data.groups.length; i++) {
      const items = this.data.groups[i].items;
      for (let j = 0; j < items.length; j++) if (items[j].name === name) return items[j];
    }
    return null;
  },

  // 只写「逐因素页拥有」的字段（描述/档次），不碰表单页基本字段与采集页照片。
  _persist() {
    const id = this.data.localId;
    if (!id) return Promise.resolve();
    return store.loadDraftLocal(id).then((d) => {
      const draft = store.assign(d || { id, dirty: true, status: '草稿' }, {
        id, assetConditions: this.data.descs, subjectLevels: this.data.levels, dirty: true,
      });
      return store.saveDraftLocal(draft);
    });
  },

  onDone() { this._persist().then(() => dd.navigateBack()); },
});
