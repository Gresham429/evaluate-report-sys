// 双向同步：同字段冲突逐字段解决页。
// 表单保存遇冲突时把 {draftId, conflicts} 塞进 app.globalData.pendingConflict 并跳来这里；
// 逐条选「你的/线上」→ resolveConflict 带 resolutions 重发 saveDraft。
const app = getApp();
const store = require('../../utils/store');
const broker = require('../../utils/broker');
const sync = require('../../utils/sync');

const SECTION_LABEL = { basic: '基本信息', subject_levels: '因素档次', asset_conditions: '资产状况' };
function label(field) {
  const i = field.indexOf('.');
  if (i < 0) return field;
  const sec = SECTION_LABEL[field.slice(0, i)] || field.slice(0, i);
  return sec + '·' + field.slice(i + 1);
}
function shown(v) { return (v === null || v === undefined || v === '') ? '（空）' : String(v); }
function toItems(conflicts) {
  return (conflicts || []).map((c) => ({
    field: c.field, label: label(c.field),
    mine: shown(c.mine), theirs: shown(c.theirs),
    mineVal: c.mine, theirsVal: c.theirs, choice: 'mine',   // 默认留「你的」，但每条都须显式确认
  }));
}

Page({
  data: { draftId: '', items: [], msg: '' },

  onLoad() {
    const pc = (app.globalData && app.globalData.pendingConflict) || { draftId: '', conflicts: [] };
    this.setData({ draftId: pc.draftId || '', items: toItems(pc.conflicts) });
  },

  onPick(e) {
    const idx = e.currentTarget.dataset.idx;
    this.setData({ ['items[' + idx + '].choice']: e.currentTarget.dataset.which });
  },

  onConfirm() {
    const resolutions = {};
    this.data.items.forEach((it) => {
      resolutions[it.field] = it.choice === 'theirs' ? it.theirsVal : it.mineVal;
    });
    sync.resolveConflict(broker, store, this.data.draftId, resolutions).then((r) => {
      if (r && r.conflict) {   // 罕见：解决期间线上又变 → 重列，请再选一次
        this.setData({ items: toItems(r.conflicts), msg: '线上又有新变化，请再选一次' });
        return;
      }
      if (app.globalData) app.globalData.pendingConflict = null;
      dd.showToast({ content: '已合并保存', type: 'success', duration: 1200 });
      dd.navigateBack();
    }).catch((e) => this.setData({ msg: '保存失败：' + ((e && e.detail) || '网络错误') }));
  },

  onCancel() {
    if (app.globalData) app.globalData.pendingConflict = null;
    dd.navigateBack();
  },
});
