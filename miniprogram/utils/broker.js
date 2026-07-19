const app = getApp();

/** POST {action, payload} 到 broker，返回解析后的对象；非 2xx 抛 {status, detail}。 */
function request(action, payload) {
  return new Promise((resolve, reject) => {
    dd.httpRequest({
      url: getApp().globalData.BASE_URL + '/',
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      data: JSON.stringify({ action, payload: payload || {} }),
      dataType: 'json',
      timeout: 20000,
      success: (res) => {
        if (res.status >= 200 && res.status < 300) resolve(res.data);
        else reject({ status: res.status, detail: (res.data && res.data.error) || '请求失败' });
      },
      fail: (err) => reject({ status: 0, detail: (err && err.errorMessage) || '网络错误' }),
    });
  });
}

module.exports = { request };
