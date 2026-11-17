import cheerio from 'assets://js/lib/cheerio.min.js';

const appConfig = {
  siteName: "剧踪影院",
  siteUrl: "https://www.juzong01.me",
  parseUrl: "https://jz8.ok1333.cn"
};

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

async function init(ext) {
  console.log("初始化爬虫:", appConfig.siteName);
}

const classList = [
  { type_id: "1", type_name: "电影" },
  { type_id: "2", type_name: "剧集" },
  { type_id: "3", type_name: "综艺" },
  { type_id: "4", type_name: "动漫" }
];

const SUB_CLASS = {
  "1": [["全部", ""], ["动作", "6"], ["喜剧", "7"], ["爱情", "8"], ["科幻", "9"], ["恐怖", "10"], ["剧情", "11"], ["战争", "12"], ["犯罪", "22"], ["动画", "23"]],
  "2": [["全部", ""], ["国产剧", "13"], ["港台剧", "14"], ["日韩剧", "15"], ["欧美剧", "16"], ["海外剧", "20"]]
};

const AREA_FILTER = [
  ["全部", ""], ["大陆", "大陆"], ["香港", "香港"], ["台湾", "台湾"], ["美国", "美国"],
  ["法国", "法国"], ["英国", "英国"], ["日本", "日本"], ["韩国", "韩国"], ["德国", "德国"],
  ["泰国", "泰国"], ["印度", "印度"], ["意大利", "意大利"], ["西班牙", "西班牙"],
  ["加拿大", "加拿大"], ["其他", "其他"]
];

const SORT_FILTER = [
  ["全部", ""], ["最新更新", "time"], ["最近热播", "hits"]
];

function buildYearFilter() {
  const cur = new Date().getFullYear();
  const arr = [["全部", ""]];
  for (let y = cur; y >= 1998; y--) arr.push([String(y), String(y)]);
  return arr;
}

const YEAR_FILTER = buildYearFilter();

// TVBox 要求 filter.value 为 {n,v} 对象数组
function toFilterObj(arr) {
  return arr.map(function (g) { return { n: g[0], v: g[1] }; });
}

function buildFilters(tid) {
  return [
    { key: "sub", name: "分类", value: toFilterObj(SUB_CLASS[tid] || [["全部", ""]]) },
    { key: "area", name: "地区", value: toFilterObj(AREA_FILTER) },
    { key: "sort", name: "排序", value: toFilterObj(SORT_FILTER) },
    { key: "year", name: "年份", value: toFilterObj(YEAR_FILTER) }
  ];
}

const myFilters = {};
classList.forEach(function (c) {
  myFilters[c.type_id] = buildFilters(c.type_id);
});
// 分类路由 12 段: /vodshow/{type}-{area}-{sort}------{page}---{year}/
// 段1=type 段2=area 段3=sort 段9=page 段12=year
function buildCategoryUrl(tid, pg, filter) {
  var segs = new Array(12).fill('');
  segs[0] = String((filter.sub || '').trim() || tid);
  segs[1] = filter.area || '';
  segs[2] = filter.sort || '';
  segs[8] = String(pg || 1);
  segs[11] = filter.year || '';
  return appConfig.siteUrl + '/vodshow/' +
    segs.map(function (s) { return s ? encodeURIComponent(s) : ''; }).join('-') + '/';
}

// 搜索路由 14 段: /vodsearch/{wd}----------{page}---/  段1=wd 段11=page
function buildSearchUrl(wd, page) {
  var segs = new Array(14).fill('');
  segs[0] = String(wd || '');
  segs[10] = String(page || 1);
  return appConfig.siteUrl + '/vodsearch/' +
    segs.map(function (s) { return s ? encodeURIComponent(s) : ''; }).join('-') + '/';
}

function normalizePic(src) {
  if (!src) return '';
  if (src.indexOf('//') === 0) return 'https:' + src;
  if (src.indexOf('http') === 0) return src;
  if (src.indexOf('/') === 0) return appConfig.siteUrl + src;
  return appConfig.siteUrl + '/' + src.replace(/^\.?\//, '');
}

async function httpGet(url, referer) {
  var headers = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "identity",
    "Referer": referer || (appConfig.siteUrl + '/')
  };
  for (var i = 0; i < 3; i++) {
    try {
      var resp = await req(url, { method: "GET", headers: headers });
      var content = resp.content || '';
      if (typeof content !== 'string') content = String(content);
      if (content.length > 200) return content;
      await new Promise(function (r) { setTimeout(r, 500); });
    } catch (e) {
      console.error("httpGet失败[" + i + "]:", e.message);
      await new Promise(function (r) { setTimeout(r, 800); });
    }
  }
  return '';
}

function mergeFilter(extend, filter) {
  var out = Object.assign({}, extend);
  if (Array.isArray(filter)) {
    filter.forEach(function (f) { if (f && typeof f === 'object') Object.assign(out, f); });
  } else if (filter && typeof filter === 'object') {
    Object.assign(out, filter);
  }
  return out;
}

function parseVodList(html) {
  var $ = cheerio.load(html);
  var list = [];
  $('a.stui-vodlist__thumb').each(function () {
    var card = $(this);
    var href = card.attr('href') || '';
    var m = href.match(/voddetail\/(\d+)/);
    if (!m) return;
    var name = (card.attr('title') || '').trim();
    if (!name) name = card.find('img').attr('alt') || '';
    if (!name) return;
    var pic = card.attr('data-original') || card.find('img').attr('data-original') || card.find('img').attr('src') || '';
    var remarks = card.find('.pic-text').first().text().trim();
    list.push({
      vod_id: m[1],
      vod_name: name,
      vod_pic: normalizePic(pic),
      vod_remarks: remarks
    });
  });
  var maxPage = 0;
  $('ul.stui-page a[href]').each(function () {
    var href = $(this).attr('href') || '';
    var mm;
    mm = href.match(/\/vodshow\/([^/?#]+)/);
    if (mm) {
      var segs = mm[1].split('-');
      if (segs.length === 12) {
        var p = parseInt(segs[8], 10);
        if (!isNaN(p) && p > maxPage) maxPage = p;
      }
    }
    mm = href.match(/\/vodsearch\/([^/?#]+)/);
    if (mm) {
      var segs2 = mm[1].split('-');
      if (segs2.length === 14) {
        var p2 = parseInt(segs2[10], 10);
        if (!isNaN(p2) && p2 > maxPage) maxPage = p2;
      }
    }
  });
  var totalPage = 0;
  var tip = $('.stui-page .num').first().text().trim();
  var tipM = tip.match(/(\d+)\/(\d+)/);
  if (tipM) totalPage = parseInt(tipM[2], 10) || 0;
  var pagecount = totalPage > 0 ? totalPage : (maxPage > 0 ? maxPage : (list.length > 0 ? 1 : 0));
  return { list: list, pagecount: pagecount };
}

async function detail(id) {
  try {
    var detailUrl = id.indexOf('http') === 0 ? id : appConfig.siteUrl + '/voddetail/' + String(id).replace(/^\//, '') + '/';
    var html = await httpGet(detailUrl);
    if (!html) return JSON.stringify({ list: [] });
    var $ = cheerio.load(html);

    var vod_name = $('h1').first().text().trim();
    if (!vod_name) vod_name = $('title').text().trim().replace(/[-_—《》].*$/, '').trim();

    var picEl = $('.stui-content__thumb img').first();
    var pic = picEl.attr('data-original') || picEl.attr('src') || $('meta[property="og:image"]').attr('content') || '';

    var vod_year = '', vod_area = '', vod_class = '', vod_director = '', vod_actor = '';
    $('p.data').each(function () {
      var t = $(this).text().replace(/\s+/g, ' ').trim();
      if (t.indexOf('类型') !== -1 && !vod_class) {
        vod_class = t.split('类型')[1].split(/地区|年份/)[0].replace(/[：:]/g, '').trim();
      }
      if (t.indexOf('地区') !== -1 && !vod_area) {
        vod_area = t.split('地区')[1].split('年份')[0].replace(/[：:]/g, '').trim();
      }
      if (t.indexOf('年份') !== -1 && !vod_year) {
        vod_year = t.split('年份')[1].replace(/[：:]/g, '').trim();
      }
      if (t.indexOf('导演') !== -1 && !vod_director) {
        vod_director = t.split('导演')[1].split(/主演|类型|地区|年份|更新|简介/)[0].replace(/[：:]/g, '').trim();
      }
      if (t.indexOf('主演') !== -1 && t.indexOf('简介') === -1 && !vod_actor) {
        vod_actor = t.split('主演')[1].split(/类型|地区|年份|导演|更新|简介/)[0].replace(/[：:]/g, '').trim();
      }
    });

    var vod_content = $('.detail-sketch').first().text().replace(/\s+/g, ' ').trim();
    if (!vod_content) vod_content = $('.detail-content').first().text().replace(/\s+/g, ' ').trim();

    var groups = [];
    var lines = [];
    $('ul.stui-content__playlist').each(function () {
      var eps = [];
      $(this).find('a[href*="/vodplay/"]').each(function () {
        var h = $(this).attr('href') || '';
        var n = $(this).text().trim();
        if (!h || !n || n === '立即播放') return;
        eps.push(n + '$' + h);
      });
      if (!eps.length) return;
      groups.push(eps);
      lines.push($(this).closest('.stui-pannel').find('h3').first().text().trim());
    });
    for (var i = 0; i < groups.length; i++) {
      if (!lines[i]) lines[i] = '线路' + (i + 1);
    }

    return JSON.stringify({ list: [{
      vod_id: String(id),
      vod_name: vod_name,
      vod_pic: normalizePic(pic),
      vod_actor: vod_actor,
      vod_director: vod_director,
      vod_area: vod_area,
      vod_year: vod_year,
      vod_class: vod_class,
      vod_content: vod_content,
      vod_play_from: lines.join('$$$'),
      vod_play_url: groups.map(function (g) { return g.join('#'); }).join('$$$')
    }] });
  } catch (e) {
    console.error("详情失败:", e.message);
    return JSON.stringify({ list: [] });
  }
}

async function play(flag, id, flags) {
  var Header = { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' };
  try {
    var src = String(id || '').trim();
    if (/\.(m3u8|mp4)(\?|$)/i.test(src)) {
      return JSON.stringify({ parse: 0, url: src, Header: Header });
    }
    var playUrl = src.indexOf('http') === 0 ? src : appConfig.siteUrl + '/' + src.replace(/^\//, '');
    var html = await httpGet(playUrl);
    if (!html) return JSON.stringify({ parse: 1, Header: Header, url: playUrl });

    var pm = html.match(/var player_data=(\{[\s\S]*?\})/);
    var player = null;
    if (pm) {
      try { player = JSON.parse(pm[1]); } catch (e) { player = null; }
    }
    if (!player) {
      var um = html.match(/"url"\s*:\s*"([^"]*)"/);
      player = { url: um ? um[1] : '' };
    }
    var token = String(player.url || '').trim();
    if (!token) return JSON.stringify({ parse: 1, Header: Header, url: playUrl });
    if (/^https?:\/\//i.test(token)) {
      return JSON.stringify({ parse: 0, url: token, Header: Header });
    }

    var page = await httpGet(appConfig.parseUrl + '/?url=' + encodeURIComponent(token), appConfig.siteUrl + '/');
    var tm = page.match(/WGART_PARSE_TOKEN="([^"]*)"/);
    if (!tm) return JSON.stringify({ parse: 1, Header: Header, url: playUrl });
    var parseToken = tm[1];
    var apiUrl = appConfig.parseUrl + '/wgart/api.php?action=try_json_api&video_url=' + encodeURIComponent(token) + '&parse_token=' + encodeURIComponent(parseToken);
    var j = await httpGet(apiUrl, appConfig.parseUrl + '/');
    var data = null;
    try { data = JSON.parse(j); } catch (e) { data = null; }
    var real = (data && data.data && data.data.url) || '';
    if (!real) return JSON.stringify({ parse: 1, Header: Header, url: playUrl });
    if (/\.(m3u8|mp4)(\?|$)/i.test(real)) {
      return JSON.stringify({ parse: 0, url: real, Header: Header });
    }
    return JSON.stringify({ parse: 1, Header: Header, url: real });
  } catch (e) {
    console.error("播放失败:", e.message);
    return JSON.stringify({ parse: 1, Header: Header, url: String(id || '') });
  }
}

async function home(filter) {
  var list = [];
  try {
    var html = await httpGet(appConfig.siteUrl + '/');
    list = parseVodList(html).list.slice(0, 30);
  } catch (e) {
    console.error("首页失败:", e.message);
  }
  return JSON.stringify({ class: classList, filters: myFilters, list: list });
}

async function category(tid, pg, filter, extend) {
  try {
    var merged = mergeFilter(extend || {}, filter);
    var url = buildCategoryUrl(tid, pg || 1, merged);
    var html = await httpGet(url);
    var r = parseVodList(html);
    return JSON.stringify({ list: r.list, pagecount: r.pagecount });
  } catch (e) {
    console.error("分类失败:", e.message);
    return JSON.stringify({ list: [], pagecount: 0 });
  }
}

async function search(wd, quick, page) {
  try {
    var kw = String(wd || '').trim();
    if (!kw) return JSON.stringify({ list: [], pagecount: 0 });
    var url = buildSearchUrl(kw, page || 1);
    var html = await httpGet(url);
    if (!html) return JSON.stringify({ list: [], pagecount: 0 });
    var r = parseVodList(html);
    return JSON.stringify({ list: r.list, pagecount: r.pagecount });
  } catch (e) {
    console.error("搜索失败:", e.message);
    return JSON.stringify({ list: [], pagecount: 0 });
  }
}

export default { init: init, home: home, category: category, detail: detail, search: search, play: play };
