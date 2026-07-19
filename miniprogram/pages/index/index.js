const broker = require('../../utils/broker');
const app = getApp();

/** ISO 时间戳 → "MM-DD HH:mm"（列表展示用，去掉原始 T/毫秒/Z）。 */
function fmtTime(s) {
  const t = String(s || '');
  return t.length >= 16 ? t.slice(5, 16).replace('T', ' ') : t;
}

Page({
  data: { filler: '', fillerName: '', authError: '', drafts: [] },

  onLoad() { this.auth(); },
  onShow() { this.loadMyDrafts(); },

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

  loadMyDrafts() {
    dd.getStorage({
      key: 'myDrafts',
      success: (res) => {
        const ids = res.data || [];
        Promise.all(ids.map((id) =>
          broker.request('loadDraft', { survey_id: id })
            .then((d) => ({ survey_id: id, category: d.category,
              status: d.status || '', updated_at: fmtTime(d.updated_at) }))
            .catch(() => null)
        )).then((rows) => this.setData({ drafts: rows.filter(Boolean) }));
      },
      fail: () => this.setData({ drafts: [] }),
    });
  },

  onNew() { dd.navigateTo({ url: '/pages/form/form' }); },
  onResume(e) { dd.navigateTo({ url: '/pages/form/form?draftId=' + e.currentTarget.dataset.id }); },
});
