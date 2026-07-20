const broker = require('../../utils/broker');
const store = require('../../utils/store');

const MAX_PHOTOS = 9;

Page({
  data: {
    localId: '',
    photos: [],     // 已上传：URL 串（进 content.photos）
    pending: [],     // 待上传：{name, dataBase64, path}（仅本机，联网/回表单时补传）
    gps: null, geo: {}, msg: '',
  },

  onLoad(q) {
    const id = (q && q.draftId) || '';
    this.setData({ localId: id });
    if (id) store.loadDraftLocal(id).then((d) => {
      if (d) this.setData({ photos: d.photos || [], pending: d.pendingPhotos || [],
        gps: d.gps || null, geo: d.geo || {} });
    });
  },

  onChoose() {
    const room = MAX_PHOTOS - (this.data.photos.length + this.data.pending.length);
    if (room <= 0) { this.setData({ msg: '最多 ' + MAX_PHOTOS + ' 张' }); return; }
    dd.chooseImage({
      count: room,
      success: (res) => this._ingest(res.filePaths || res.tempFilePaths || res.apFilePaths || []),
      fail: (e) => this.setData({ msg: '选图失败：' + ((e && e.errorMessage) || '') }),
    });
  },

  // 逐张：压缩 → 读 base64 → 联网则即传得 URL，否则入待传队列；每张处理完即持久化不丢。
  _ingest(paths) {
    let chain = Promise.resolve();
    paths.forEach((p) => { chain = chain.then(() => this._ingestOne(p)); });
    chain.then(() => this._persist());
  },
  _ingestOne(path) {
    return _compress(path).then((cpath) => _readBase64(cpath).then((b64) => {
      const name = 'photo-' + Date.now() + '.jpg';
      return broker.request('uploadPhoto', { name, dataBase64: b64 })
        .then((r) => this.setData({ photos: this.data.photos.concat([r.url]) }))
        .catch(() => this.setData({
          pending: this.data.pending.concat([{ name, dataBase64: b64, path: cpath }]),
          msg: '当前离线，照片已存本机，联网自动补传',
        }));
    })).catch((e) => this.setData({ msg: '读图失败：' + ((e && e.message) || '') }));
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
          this._persist();
        }).catch((e) => { this._persist(); this.setData({ msg: '地图预填失败：' + e.detail }); });
      },
      fail: (e) => this.setData({ msg: '取定位失败：' + ((e && e.errorMessage) || '') }),
    });
  },

  onDelPhoto(e) {
    const i = e.currentTarget.dataset.i;
    const photos = this.data.photos.slice(); photos.splice(i, 1);
    this.setData({ photos }); this._persist();
  },
  onDelPending(e) {
    const i = e.currentTarget.dataset.i;
    const pending = this.data.pending.slice(); pending.splice(i, 1);
    this.setData({ pending }); this._persist();
  },

  // 只写「采集页拥有」的字段（照片/定位/地理），不碰表单页的基本字段。
  _persist() {
    const id = this.data.localId;
    if (!id) return Promise.resolve();
    return store.loadDraftLocal(id).then((d) => {
      const draft = store.assign(d || { id, dirty: true, status: '草稿' }, {
        id, photos: this.data.photos, pendingPhotos: this.data.pending,
        gps: this.data.gps, geo: this.data.geo, dirty: true,
      });
      return store.saveDraftLocal(draft);
    });
  },

  onDone() { this._persist().then(() => dd.navigateBack()); },
});

// —— dd 文件/压缩 API 待真机校准（不同基础库版本 API 名/返回字段可能不同）——
function _compress(path) {
  return new Promise((resolve) => {
    if (dd.compressImage) {
      dd.compressImage({ apFilePaths: [path], compressLevel: 4,
        success: (r) => resolve((r.apFilePaths || [path])[0]), fail: () => resolve(path) });
    } else { resolve(path); }
  });
}
function _readBase64(path) {
  return new Promise((resolve, reject) => {
    const fs = dd.getFileSystemManager && dd.getFileSystemManager();
    if (fs && fs.readFile) {
      fs.readFile({ filePath: path, encoding: 'base64',
        success: (r) => resolve(r.data), fail: (e) => reject(new Error((e && e.errorMessage) || 'read')) });
    } else { reject(new Error('无文件读取 API（待真机校准）')); }
  });
}
