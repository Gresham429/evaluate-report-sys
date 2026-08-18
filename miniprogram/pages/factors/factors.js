const broker = require('../../utils/broker');
const store = require('../../utils/store');
const FACTORS = require('../../factors');

// 地图地理事实 → 区位因素描述的关键字映射（只把事实填进对应因素的「描述」，
// 档次仍由估价师手选下拉，铁律 #7）。顺序＝匹配优先级（具体在前）。
// 「临街道路」须排在「临街」前：临街道路等级取道路名，临街状况取四至。
const GEO_MAP = [
  { kw: '地铁', pick: (geo) => geo.metroText },
  { kw: '公交', pick: (geo) => geo.busText },
  { kw: '公共服务设施', pick: (geo) => geo.facilities },
  { kw: '高速', pick: (geo) => geo.highwayText },
  { kw: '城中心', pick: (geo) => geo.centerText },
  { kw: '重要场所', pick: (geo) => geo.centerText },
  { kw: '水源', pick: (geo) => geo.waterText },
  { kw: '停车', pick: (geo) => geo.parkingText },
  { kw: '临街道路', pick: (geo) => geo.roadsText },   // 临街道路等级 → 就近道路名
  { kw: '临街', pick: (geo) => geo.bordersText },      // 临街状况 → 四至 + 临街
  { kw: '道路', pick: (geo) => geo.roadsText },
  { kw: '临路', pick: (geo) => geo.roadsText },
];

/** 米 → 「约X.X公里 / 约X米」。 */
function _dist(m) {
  const n = Number(m) || 0;
  return n >= 1000 ? ('约' + (Math.round(n / 100) / 10) + '公里') : ('约' + Math.round(n) + '米');
}

/** 200 米内公交 → 「712、723、733路公交车」；无线路则退回站点数（线路现场补）。 */
function _busText(f) {
  const lines = f.bus_lines || [];
  if (lines.length) {
    return lines.map((s) => String(s).replace(/路$/, '')).join('、') + '路公交车';
  }
  if (f.bus_stop_count) return '附近有公交站' + f.bus_stop_count + '处（线路请现场核对）';
  return '（无）';
}

/** 公共服务设施 → 「附近学校有…；医院有…；银行有…；商场有…。」（只列非空类别）。 */
function _facilitiesText(fac) {
  const groups = [['schools', '学校'], ['hospitals', '医院'], ['banks', '银行'], ['malls', '商场']];
  const parts = [];
  groups.forEach((g) => {
    const items = (fac && fac[g[0]]) || [];
    if (items.length) parts.push(g[1] + '有' + items.join('、'));
  });
  return parts.length ? ('附近' + parts.join('；') + '。') : '';
}

/** 临街状况 → 「估价对象所在宗地东至…南至…西至…北至…。估价对象临A、B。」（草稿，请核对）。 */
function _bordersText(f) {
  const bd = f.bordering || {};
  const dirs = [['东', '东至'], ['南', '南至'], ['西', '西至'], ['北', '北至']];
  const parts = [];
  dirs.forEach((d) => { if (bd[d[0]]) parts.push(d[1] + bd[d[0]]); });
  let s = '';
  if (parts.length) s += '估价对象所在宗地' + parts.join('，') + '。';
  const roads = f.roads || [];
  if (roads.length) s += '估价对象临' + roads.slice(0, 2).join('、') + '。';
  return s;
}

/** 高德 facts → 展示/预填用的文字字段。 */
function _geoTexts(f) {
  const metro = f.nearest_metro, hw = f.highway, ctr = f.center, pk = f.parking;
  return {
    address: f.address,
    bus_stops: (f.bus_stops || []).join('、') || '（无）',   // 展示：站名
    busText: _busText(f),                                    // 预填：线路号
    facilities: _facilitiesText(f.facilities),               // 展示 & 预填：四类
    bordersText: _bordersText(f),                            // 预填：临街四至
    metroText: metro ? (metro.name + ' ' + _dist(metro.distance_m)) : '（无）',
    highwayText: hw ? (hw.name + ' ' + _dist(hw.distance_m)) : '',
    centerText: ctr ? (ctr.name + ' ' + _dist(ctr.distance_m)) : '',
    waterText: f.water ? (f.water.name + ' ' + _dist(f.water.distance_m)) : '',
    parkingText: pk ? ('周边约' + pk.count + '个停车场'
      + (pk.nearest_m ? ('，最近' + _dist(pk.nearest_m)) : '')) : '',
    roadsText: (f.roads && f.roads.length) ? ('临近：' + f.roads.join('、')) : '',
  };
}

// 逐因素采集：按类别渲染各因素「描述(自由文字)+档次(下拉，取自基础表)」+ 地图预填。
// 描述→content.asset_conditions[因素名]；档次→content.subject_levels[因素名]；键对齐办公端。
Page({
  data: {
    localId: '', category: '',
    groups: [],               // [{section, items:[{name, levels:[...]}]}]
    descs: {}, levels: {},    // 因素名 → 描述 / 档次
    gps: null, geo: {},       // 地图预填（从采集页移来）
  },

  onLoad(q) {
    const id = (q && q.draftId) || '';
    this.setData({ localId: id });
    if (id) store.loadDraftLocal(id).then((d) => {
      const cat = (d && d.category) || (q && q.category) || '';
      this.setData({
        category: cat, groups: FACTORS[cat] || [],
        descs: (d && d.assetConditions) || {}, levels: (d && d.subjectLevels) || {},
        gps: (d && d.gps) || null, geo: (d && d.geo) || {},
      });
      if (d && d.geo && d.geo.address) this._prefillFromGeo(d.geo);   // 已有地图事实则补空描述
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

  // 地图预填（移自采集页）：取 GPS → 地理事实 → 展示 + 自动填入对应区位因素的空描述。
  onGeo() {
    dd.getLocation({
      success: (loc) => {
        this.setData({ gps: { lat: loc.latitude, lng: loc.longitude } });
        broker.request('prefillGeo', { lng: loc.longitude, lat: loc.latitude }).then((f) => {
          const geo = _geoTexts(f);
          this.setData({ geo });
          this._prefillFromGeo(geo);
          this._persist();
        }).catch((e) => { this._persist(); this.setData({ msg: '地图预填失败：' + e.detail }); });
      },
      fail: (e) => this.setData({ msg: '取定位失败：' + ((e && e.errorMessage) || '') }),
    });
  },

  // 地图事实 → 对应区位因素的描述，只填空、不覆盖估价师已写的；档次不动。
  _prefillFromGeo(geo) {
    if (!geo) return;
    const patch = {};
    this.data.groups.forEach((g) => g.items.forEach((it) => {
      if (this.data.descs[it.name]) return;   // 已有描述不覆盖
      let val = '';
      for (let i = 0; i < GEO_MAP.length; i++) {
        if (it.name.indexOf(GEO_MAP[i].kw) >= 0) { val = GEO_MAP[i].pick(geo) || ''; break; }
      }
      if (val && val !== '（无）') patch['descs.' + it.name] = val;
    }));
    if (Object.keys(patch).length) { this.setData(patch); this._persist(); }
  },

  // 只写「逐因素页拥有」的字段（描述/档次/地图），不碰表单页基本字段与采集页照片。
  _persist() {
    const id = this.data.localId;
    if (!id) return Promise.resolve();
    return store.loadDraftLocal(id).then((d) => {
      const draft = store.assign(d || { id, dirty: true, status: '草稿' }, {
        id, assetConditions: this.data.descs, subjectLevels: this.data.levels,
        gps: this.data.gps, geo: this.data.geo, dirty: true,
      });
      return store.saveDraftLocal(draft);
    });
  },

  onDone() { this._persist().then(() => dd.navigateBack()); },
});
