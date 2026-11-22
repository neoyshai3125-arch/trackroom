const assert = require('node:assert/strict');
const path = require('node:path');
const src = path.join(__dirname,'../public/native-streaming.js');
const assign = [];
const documentHandlers = {};
const windowHandlers = {};
const panels = [];
Object.defineProperty(globalThis,'navigator',{value:{userAgent:'Mozilla/5.0 TRACKROOMAndroid/0.1'},configurable:true});
globalThis.localStorage = {getItem(){return 'melon';},setItem(){}};
globalThis.document = {
  documentElement:{classList:{add(name){assert.equal(name,'trackroom-android')}}},
  addEventListener(type, fn){ documentHandlers[type] = fn; },
  querySelectorAll() { return panels; }
};
globalThis.CustomEvent = class {constructor(type, details){this.type=type;this.detail=details.detail;}};
globalThis.window = {
  addEventListener(type, fn){windowHandlers[type]=fn},
  location:{assign(url){assign.push(url)}},
  dispatchEvent(){}
};
require(src);
const p=window.TrackroomStreaming;
assert.equal(p.enabled,true);
assert.match(p.controls({title:'METEOR',artist:'창모'}),/멜론/);
assert.match(p.controls({title:'METEOR',artist:'창모'}),/trackroom-media-panel/);
assert.equal(p.play({title:'METEOR',artist:'창모',musicUrl:'https://music.apple.com/'},'melon'),true);
assert.equal(p.play({title:'METEOR',artist:'창모'},'invalid'),false);
assert.equal(assign.length,1);
let url=new URL(assign[0]);
assert.equal(url.protocol,'trackroom-native:');
assert.equal(url.hostname,'play');
assert.equal(url.searchParams.get('artist'),'창모');
assert.equal(url.searchParams.get('provider'),'melon');
assert.equal(p.send('play', {provider:'melon'}),true);
url=new URL(assign[1]);
assert.equal(url.hostname,'media');
assert.equal(url.searchParams.get('action'),'play');
windowHandlers['trackroom:media-session']({detail:{provider:'melon', permission:true, connected:true, title:'METEOR', artist:'창모', positionMs:60000, durationMs:180000, state:'playing'}});
assert.equal(p.state().title, 'METEOR');
assert.equal(p.formatTime(60000),'1:00');
console.log('Android MediaSession hand-off JS smoke: OK');
