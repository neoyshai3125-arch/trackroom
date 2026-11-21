const assert = require('node:assert/strict');
const path = require('node:path');
const src = path.join(__dirname,'../public/native-streaming.js');
const assign = [];
Object.defineProperty(globalThis,'navigator',{value:{userAgent:'Mozilla/5.0 TRACKROOMAndroid/0.1'},configurable:true});
globalThis.localStorage = {getItem(){return 'melon';},setItem(){}};
globalThis.document = {
  documentElement:{classList:{add(name){assert.equal(name,'trackroom-android')}}},
  addEventListener(type){assert.equal(type,'click')}
};
globalThis.window = {
  addEventListener(type){assert.equal(type,'trackroom:native-result')},
  location:{assign(url){assign.push(url)}},
  dispatchEvent(){}
};
require(src);
const p=window.TrackroomStreaming;
assert.equal(p.enabled,true);
assert.match(p.controls({title:'METEOR',artist:'창모'}),/멜론/);
assert.equal(p.play({title:'METEOR',artist:'창모',musicUrl:'https://music.apple.com/'},'melon'),true);
assert.equal(p.play({title:'METEOR',artist:'창모'},'invalid'),false);
assert.equal(assign.length,1);
const url=new URL(assign[0]);
assert.equal(url.protocol,'trackroom-native:');
assert.equal(url.hostname,'play');
assert.equal(url.searchParams.get('artist'),'창모');
assert.equal(url.searchParams.get('provider'),'melon');
console.log('Android hand-off JS smoke: OK');
