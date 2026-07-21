const broker = require('../../utils/broker');
const store = require('../../utils/store');
const sync = require('../../utils/sync');
const app = getApp();

/** ISO 时间戳 → "MM-DD HH:mm"（列表展示用，去掉原始 T/毫秒/Z）。 */
function fmtTime(s) {
  const t = String(s || '');
  return t.length >= 16 ? t.slice(5, 16).replace('T', ' ') : t;
}

Page({
  // drafts=未提交（可删）；submittedGroups=已提交按类别分组（不可删）
  data: { filler: '', fillerName: '', authError: '', drafts: [], submittedGroups: [] },

  onLoad() { this.auth(); },
  onShow() { sync.flush(broker, store); this.loadMyDrafts(); },

  auth() {
    dd.getAuthCode({
      success: (r) => {
        broker.request('whoami', { authCode: r.authCode })
          .then((who) => {
            app.globalData.filler = who.userid;
            app.globalData.fillerName = who.name || '';
            this.setData({ filler: who.userid, fillerName: who.name || '' });
            this.loadMyDrafts();   // 免登拿到 filler 后再拉「我的问卷」(跨设备)
          })
          .catch((e) => this.setData({ authError: e.detail || '未知' }));
      },
      fail: (e) => this.setData({ authError: (e && e.errorMessage) || '取 authCode 失败' }),
    });
  },

  // 本地索引秒出 → 联网拉「我的问卷」(按填报人,含跨设备/别的设备提交的)对账刷新
  loadMyDrafts() {
    store.migrateLegacy().then((list) => {
      this._render(list);                    // 本地秒出
      const filler = app.globalData.filler;
      if (!filler) return;                   // 免登未完成，先只显本地（auth 完成会再调）
      broker.request('listSurveys', { filler }).then((r) => {
        const rows = (r.surveys || []).map((s) => ({ survey_id: s.survey_id,
          category: s.category, status: s.status || '', updated_at: s.updated_at || '' }));
        store.reconcileFromServer(rows).then((merged) => this._render(merged));
      }).catch(() => {});                     // 离线：保留本地渲染
    });
  },

  _render(list) {
    const rows = this._toRows(list);
    const drafts = rows.filter((r) => !r.submitted);
    const submitted = rows.filter((r) => r.submitted);
    const map = {}, order = [];
    submitted.forEach((r) => {
      if (!map[r.category]) { map[r.category] = []; order.push(r.category); }
      map[r.category].push(r);
    });
    const submittedGroups = order.map((c) => ({ category: c, rows: map[c] }));
    this.setData({ drafts, submittedGroups });
  },

  // 索引 → 列表行：按 updatedAt 倒序；状态本地优先（未同步/已提交）。
  _toRows(list) {
    return (list || []).slice()
      .sort((a, b) => String(b.updatedAt || '').localeCompare(String(a.updatedAt || '')))
      .map((e) => ({
        open_id: e.id,                       // 续填用（本地内容 key）
        survey_id: e.serverId || e.id,
        category: e.category || '（未选类别）',
        status: e.submitted ? '已提交' : (e.dirty ? '未同步' : (e.status || '草稿')),
        submitted: !!e.submitted,
        updated_at: fmtTime(e.updatedAt),
      }));
  },

  onNew() { dd.navigateTo({ url: '/pages/form/form' }); },
  onResume(e) { dd.navigateTo({ url: '/pages/form/form?draftId=' + e.currentTarget.dataset.id }); },

  // 删未提交草稿：确认 → 删本地 → 在线则best-effort删服务端草稿行 → 刷新
  onDelete(e) {
    const id = e.currentTarget.dataset.id;
    dd.confirm({
      title: '删除草稿',
      content: '删除这份未提交的草稿？不可恢复。',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      success: (r) => { if (r.confirm) this._doDelete(id); },
    });
  },
  _doDelete(id) {
    store.deleteDraft(id).then((serverId) => {
      if (serverId) broker.request('deleteDraft', { survey_id: serverId }).catch(() => {});
      this.loadMyDrafts();
    });
  },
});
