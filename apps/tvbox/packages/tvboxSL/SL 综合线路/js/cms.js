import { req } from 'assets://js/lib/cat.js';

let siteKey = '';
let HOST = '';
let classCache = null;

const UA = 'okhttp/3.15';

// 成人分类判定：命中任一词即整类剔除，对应分类页直接返回空
const ADULT = /理论|伦理|成人|福利|情色|色情|三级|写真|里番|无码|有码|自拍|偷拍|约炮|激情|男同|女同|同志|啪啪|裸|艳照|淫|擦边|两性/;
// 非影视分类（新闻/资讯/爆料/评论），一并剔除
const NONVIDEO = /新闻|资讯|动态|爆料|公告|专题|评论|八卦/;

// 站点 key → 上游 CMS 地址（一个脚本服务全部包装站）
const HOSTS = {
    'std_js_vod_360zy': 'https://360zy.com/api.php/provide/vod',
    'std_js_vod_baofeng': 'https://bfzyapi.com/api.php/provide/vod',
    'std_js_vod_tiantang': 'https://caiji.dyttzyapi.com/api.php/provide/vod',
    'std_js_vod_liangzi': 'http://cj.lziapi.com/api.php/provide/vod',
    'std_js_vod_ruyi': 'https://www.ryzyw.com/api.php/provide/vod',
    'std_js_vod_zuida': 'https://api.zuidapi.com/api.php/provide/vod',
    'std_js_vod_suoni': 'https://suoniapi.com/api.php/provide/vod',
    'std_js_vod_huohu': 'https://hhzyapi.com/api.php/provide/vod',
    'std_js_vod_jisu': 'https://jszyapi.com/api.php/provide/vod',
    'std_js_vod_hongniu': 'https://www.hongniuzy2.com/api.php/provide/vod',
    'std_js_vod_jinying': 'https://jyzyapi.com/api.php/provide/vod',
    'std_js_vod_huya': 'https://www.huyaapi.com/api.php/provide/vod',
    'std_js_vod_piaoling': 'https://p2100.net/api.php/provide/vod',
    'std_js_vod_ikun': 'https://ikunzy.cc/api.php/provide/vod',
    'std_js_vod_iqiyi': 'https://iqiyizyapi.com/api.php/provide/vod',
    'std_js_vod_modu': 'https://www.mdzyapi.com/api.php/provide/vod',
    'std_js_vod_xigua': 'https://xiguazy.tv/api.php/provide/vod',
    'std_js_vod_maoyan': 'https://api.maoyanapi.top/api.php/provide/vod',
    'std_js_vod_feifan': 'https://api.ffzyapi.com/api.php/provide/vod',
    'std_js_vod_wujin': 'https://api.wujinapi.com/api.php/provide/vod',
    'std_js_vod_niuniu': 'https://api.niuniuzy.me/api.php/provide/vod'
};

function isAdult(text) {
    return ADULT.test(String(text || ''));
}

function apiUrl(query) {
    return HOST + (HOST.indexOf('?') >= 0 ? '&' : '?') + query;
}

async function getJson(query) {
    const res = await req(apiUrl(query), {
        method: 'get',
        headers: { 'User-Agent': UA }
    });
    return JSON.parse(res.content);
}

async function classes() {
    if (classCache) return classCache;
    const data = await getJson('ac=list');
    const src = (data && data.class) || [];
    const parentIds = {};
    for (let i = 0; i < src.length; i++) {
        const pid = src[i] ? src[i].type_pid : 0;
        if (pid && String(pid) !== '0') parentIds[String(pid)] = true;
    }
    const list = [];
    for (let i = 0; i < src.length; i++) {
        const item = src[i] || {};
        if (item.type_id === undefined || item.type_id === null) continue;
        const name = String(item.type_name || '').trim();
        if (!name) continue;
        const id = String(item.type_id);
        list.push({
            type_id: item.type_id,
            type_name: name,
            adult: isAdult(name),
            nonvideo: NONVIDEO.test(name),
            parent: parentIds[id] === true
        });
    }
    classCache = list;
    return list;
}

function mapList(list) {
    const out = [];
    for (let i = 0; i < list.length; i++) {
        const v = list[i] || {};
        if (isAdult(v.type_name) || isAdult(v.vod_name)) continue;
        out.push({
            vod_id: v.vod_id,
            vod_name: v.vod_name,
            vod_pic: v.vod_pic || '',
            vod_remarks: v.vod_remarks || ''
        });
    }
    return out;
}

async function init(cfg) {
    siteKey = cfg && cfg.skey ? cfg.skey : '';
    HOST = HOSTS[siteKey] || '';
    classCache = null;
}

async function home(filter) {
    const ok = [];
    const filters = {};
    try {
        const all = await classes();
        for (let i = 0; i < all.length; i++) {
            if (all[i].adult || all[i].nonvideo) continue;
            if (all[i].parent) continue;
            ok.push({ type_id: all[i].type_id, type_name: all[i].type_name });
            filters[all[i].type_id] = [];
        }
    } catch (e) {
    }
    return JSON.stringify({ class: ok, filters: filters });
}

async function homeVod() {
    try {
        const data = await getJson('ac=detail&pg=1');
        return JSON.stringify({ list: mapList(data.list || []).slice(0, 20) });
    } catch (e) {
        return JSON.stringify({ list: [] });
    }
}

async function category(tid, pg, filter, extend) {
    if (!pg || pg < 1) pg = 1;
    try {
        const all = await classes();
        let target = null;
        for (let i = 0; i < all.length; i++) {
            if (String(all[i].type_id) === String(tid)) { target = all[i]; break; }
        }
        if (!target || target.adult || target.nonvideo || target.parent) {
            return JSON.stringify({ page: 1, pagecount: 1, limit: 20, total: 0, list: [] });
        }
        const data = await getJson('ac=detail&t=' + encodeURIComponent(tid) + '&pg=' + pg);
        return JSON.stringify({
            page: parseInt(data.page || pg),
            pagecount: parseInt(data.pagecount || 1),
            limit: parseInt(data.limit || 20),
            total: parseInt(data.total || 0),
            list: mapList(data.list || [])
        });
    } catch (e) {
        return JSON.stringify({ page: 1, pagecount: 1, limit: 20, total: 0, list: [] });
    }
}

async function detail(id) {
    try {
        const data = await getJson('ac=detail&ids=' + encodeURIComponent(id));
        const list = data.list || [];
        for (let i = 0; i < list.length; i++) {
            const v = list[i] || {};
            if (isAdult(v.type_name) || isAdult(v.vod_name)) continue;
            return JSON.stringify({ list: [v] });
        }
    } catch (e) {
    }
    return JSON.stringify({ list: [] });
}

async function search(wd, quick) {
    try {
        const data = await getJson('ac=detail&wd=' + encodeURIComponent(wd));
        return JSON.stringify({ list: mapList(data.list || []) });
    } catch (e) {
        return JSON.stringify({ list: [] });
    }
}

async function play(flag, id, flags) {
    return JSON.stringify({ parse: 0, url: id, header: {} });
}

export { init, home, homeVod, category, detail, search, play };
