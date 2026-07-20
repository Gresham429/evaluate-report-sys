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
  data: { filler: '', fillerName: '', authError: '', drafts: [] },

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
          })
          .catch((e) => this.setData({ authError: e.detail || '未知' }));
      },
      fail: (e) => this.setData({ authError: (e && e.errorMessage) || '取 authCode 失败' }),
    });
  },

  // 本地索引秒出 → 联网对账刷新（离线则止于本地）
  loadMyDrafts() {
    store.migrateLegacy().then((list) => {
      this.setData({ drafts: this._toRows(list) });
      const withServer = list.filter((e) => e.serverId && !e.submitted);
      if (!withServer.length) return;
      Promise.all(withServer.map((e) =>
        broker.request('loadDraft', { survey_id: e.serverId })
          .then((d) => ({ survey_id: e.serverId, category: d.category,
            status: d.status || '', updated_at: d.updated_at || '' }))
          .catch(() => null)
      )).then((rows) => {
        const ok = rows.filter(Boolean);
        if (!ok.length) return;   // 全失败＝离线，保留本地渲染
        store.reconcileFromServer(ok).then((merged) =>
          this.setData({ drafts: this._toRows(merged) }));
      });
    });
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
        updated_at: fmtTime(e.updatedAt),
      }));
  },

  onNew() { dd.navigateTo({ url: '/pages/form/form' }); },
  onResume(e) { dd.navigateTo({ url: '/pages/form/form?draftId=' + e.currentTarget.dataset.id }); },
});
