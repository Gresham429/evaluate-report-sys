const broker = require('./utils/broker');
const store = require('./utils/store');
const sync = require('./utils/sync');

App({
  globalData: {
    BASE_URL: 'https://zhenghee-report-bmpupipvct.cn-hangzhou.fcapp.run',
    filler: '',      // 免登拿到的 userid（入口页写入）
    fillerName: '',
  },

  // 网络恢复即自动补传所有「未同步」草稿（离线拍照/暂存/提交都在联网后自动补上）。
  onLaunch() {
    if (dd.onNetworkStatusChange) {
      dd.onNetworkStatusChange((res) => {
        if (res && res.isConnected) sync.flush(broker, store);
      });
    }
  },
});
