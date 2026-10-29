// Display-only: same landscape as probe.py. Never sent to the policy.
let terrainDoc=null, playback=0, playing=true, previousTime=0, runKey='', dimsKey=0, lastPaint=0, paintKey='';
const el=id=>document.getElementById(id);
const view={yaw:-0.75,pitch:0.65,zoom:1,auto:false};
let orbitPointer=null;
function setView(yaw,pitch){view.yaw=yaw;view.pitch=pitch;view.zoom=1;view.auto=false;el('autoOrbit').textContent='自动旋转';}
function orbit(dx,dy){view.yaw+=dx*.008;view.pitch=Math.max(-1.4,Math.min(Math.PI/2,view.pitch+dy*.008));}
function terrainHeight(x,target){const d=x.map((v,i)=>v-target[i]);if(terrainDoc?.objective.startsWith('parabola-'))return (terrainDoc.goal==='minimize'?1:-1)*d.reduce((sum,v)=>sum+v*v,0);return (terrainDoc?.objective==='coupled-valley-v1'?-1:1)*d.reduce((sum,v,i)=>sum-.18*v*v+1.2*Math.cos(2.3*v)+.45*Math.sin(1.4*v+.9*d[(i+1)%d.length]),0);}
function updateTerrain(doc){
  if(!['coupled-ripple-v1','coupled-valley-v1','parabola-mountain-v1','parabola-valley-v1'].includes(doc.objective)){el('slice-note').textContent='旧记录使用单峰目标，请开始一次新实验查看复杂地形。';return;}
  const key=doc.run_id||JSON.stringify(doc.warmup[0]);
  if(key!==runKey){playback=0;playing=true;runKey=key;}
  terrainDoc=doc;
  const one=doc.config.dims===1;
  el('sliceExplanation').style.display=one?'none':'';
  el('terrain').setAttribute('aria-label',one?'一维函数剖面与真实轨迹':'可旋转地形：拖动旋转，滚轮缩放，方向键旋转，Home 复位');
  document.querySelector('.view-controls').style.display=one?'none':'flex';
  document.querySelector('.orbit-help').textContent=one?'一维剖面：横轴为位置，纵轴为高度；小点与线条显示真实轨迹。':'拖动地形旋转 · 滚轮缩放 · 可从俯视、侧视和背面查看';
  for(const id of ['axisA','axisB'])el(id).parentElement.style.display=one?'none':'';
  if(dimsKey!==doc.config.dims){
    dimsKey=doc.config.dims;
    for(const id of ['axisA','axisB']){el(id).replaceChildren();for(let i=0;i<dimsKey;i++){const option=document.createElement('option');option.value=i;option.textContent='x'+i;el(id).append(option);}}
    el('axisA').value=0;el('axisB').value=Math.min(1,dimsKey-1);
  }
  el('timeline').max=doc.steps.length;
}
function initTerrain(){
  const surface=el('terrain');
  surface.onpointerdown=e=>{if(e.button!==0)return;orbitPointer={id:e.pointerId,x:e.clientX,y:e.clientY};surface.setPointerCapture(e.pointerId);surface.classList.add('dragging');};
  surface.onpointermove=e=>{if(!orbitPointer||orbitPointer.id!==e.pointerId)return;orbit(e.clientX-orbitPointer.x,e.clientY-orbitPointer.y);orbitPointer.x=e.clientX;orbitPointer.y=e.clientY;};
  const release=e=>{if(orbitPointer?.id!==e.pointerId)return;orbitPointer=null;surface.classList.remove('dragging');};
  surface.onpointerup=release;surface.onpointercancel=release;surface.onlostpointercapture=release;
  surface.addEventListener('wheel',e=>{e.preventDefault();view.zoom=Math.max(.45,Math.min(3,view.zoom*Math.exp(-e.deltaY*.001)));},{passive:false});
  surface.onkeydown=e=>{const keys=['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','Home'];if(!keys.includes(e.key))return;e.preventDefault();if(e.key==='Home')setView(-.75,.65);else if(e.key==='+'||e.key==='=')view.zoom=Math.min(3,view.zoom*1.1);else if(e.key==='-')view.zoom=Math.max(.45,view.zoom/1.1);else orbit(e.key==='ArrowLeft'?-12:e.key==='ArrowRight'?12:0,e.key==='ArrowUp'?-8:e.key==='ArrowDown'?8:0);};
  el('resetView').onclick=()=>setView(-.75,.65);
  el('topView').onclick=()=>setView(0,Math.PI/2);
  el('sideView').onclick=()=>setView(0,.12);
  el('autoOrbit').onclick=()=>{view.auto=!view.auto;el('autoOrbit').textContent=view.auto?'停止旋转':'自动旋转';};
  el('play').onclick=()=>{if(terrainDoc&&playback>=terrainDoc.steps.length)playback=0;playing=!playing;el('play').textContent=playing?'暂停回放':'播放轨迹';};
  el('timeline').oninput=()=>{playing=false;playback=Number(el('timeline').value);el('play').textContent='播放轨迹';};
  el('axisA').onchange=()=>{if(el('axisA').value===el('axisB').value)el('axisB').value=(Number(el('axisA').value)+1)%dimsKey;};
  el('axisB').onchange=()=>{if(el('axisA').value===el('axisB').value)el('axisA').value=(Number(el('axisB').value)+1)%dimsKey;};
  requestAnimationFrame(animateTerrain);
}
function animateTerrain(now){
  const dt=Math.min(.1,(now-previousTime)/1000);previousTime=now;
  if(terrainDoc){
    if(view.auto&&!orbitPointer)view.yaw+=dt*.3;
    if(playing)playback=Math.min(terrainDoc.steps.length,playback+dt*1.3);
    const key=[runKey,playback.toFixed(2),el('axisA').value,el('axisB').value,el('terrain').clientWidth,view.yaw,view.pitch,view.zoom].join('|');
    if(now-lastPaint>66&&key!==paintKey){drawTerrain(terrainDoc,playback);el('timeline').value=playback;lastPaint=now;paintKey=key;}
    if(playing&&terrainDoc.status!=='running'&&playback>=terrainDoc.steps.length){playing=false;el('play').textContent='重新播放';}
  }
  requestAnimationFrame(animateTerrain);
}
function drawTerrain(doc,t){
  const c=el('terrain'),ratio=devicePixelRatio||1,w=c.clientWidth,h=420;
  if(c.width!==Math.round(w*ratio)||c.height!==Math.round(h*ratio)){c.width=Math.round(w*ratio);c.height=Math.round(h*ratio);c.style.height=h+'px';}
  const g=c.getContext('2d');g.setTransform(ratio,0,0,ratio,0,0);g.clearRect(0,0,w,h);
  const rows=[doc.warmup.at(-1),...doc.steps],index=Math.min(Math.floor(t),rows.length-1),next=Math.min(index+1,rows.length-1),f=t-index;
  const state=rows[index].x.map((v,i)=>v+(rows[next].x[i]-v)*f);
  if(doc.config.dims===1){drawProfile(g,w,h,doc,rows,index,state,t);return;}
  const a=Number(el('axisA').value),b=Number(el('axisB').value),target=doc.target_evaluation_only;
  if(a===b){g.fillStyle='#a7b8cc';g.fillText('请选择两个不同的坐标',30,40);return;}
  // Same world bounds throughout a run, expanded only when the trajectory leaves them.
  const av=rows.map(r=>r.x[a]),bv=rows.map(r=>r.x[b]);
  const amin=Math.min(-4,...av.map(v=>v-1)),amax=Math.max(4,...av.map(v=>v+1));
  const bmin=Math.min(-4,...bv.map(v=>v-1)),bmax=Math.max(4,...bv.map(v=>v+1));
  const n=32,mesh=[];let low=Infinity,high=-Infinity;
  for(let j=0;j<=n;j++){const row=[];for(let i=0;i<=n;i++){const x=state.slice();x[a]=amin+(amax-amin)*i/n;x[b]=bmin+(bmax-bmin)*j/n;const z=terrainHeight(x,target);low=Math.min(low,z);high=Math.max(high,z);row.push(z);}mesh.push(row);}
  const span=Math.max(1,high-low),scale=Math.min(w*.29,175)*view.zoom;
  const cy=Math.cos(view.yaw),sy=Math.sin(view.yaw),cp=Math.cos(view.pitch),sp=Math.sin(view.pitch);
  function project(u,v,z){const x=2*u-1,y=2*v-1,vertical=((z-low)/span-.5)*.85;
    const horizontal=cy*x-sy*y,depth=sy*x+cy*y;
    return [w/2+horizontal*scale,h*.53+(depth*sp-vertical*cp)*scale,depth*cp+vertical*sp];}
  // Sort in camera space for every angle, including views below the surface.
  const faces=[];
  for(let j=0;j<n;j++)for(let i=0;i<n;i++){
    const values=[mesh[j][i],mesh[j][i+1],mesh[j+1][i+1],mesh[j+1][i]],average=values.reduce((x,y)=>x+y,0)/4;
    const shade=(average-low)/span,points=[project(i/n,j/n,values[0]),project((i+1)/n,j/n,values[1]),project((i+1)/n,(j+1)/n,values[2]),project(i/n,(j+1)/n,values[3])];
    faces.push({points,shade,depth:points.reduce((sum,p)=>sum+p[2],0)/4});
  }
  faces.sort((a,b)=>a.depth-b.depth);
  for(const {points,shade} of faces){g.beginPath();points.forEach(([x,y],k)=>k?g.lineTo(x,y):g.moveTo(x,y));g.closePath();g.fillStyle=`hsl(${205-shade*145} 42% ${20+shade*37}%)`;g.fill();g.strokeStyle='#ffffff14';g.lineWidth=.5;g.stroke();}
  const pointFor=(x)=>{const onSlice=state.slice();onSlice[a]=x[a];onSlice[b]=x[b];return project((x[a]-amin)/(amax-amin),(x[b]-bmin)/(bmax-bmin),terrainHeight(onSlice,target));};
  const path=[...rows.slice(0,index+1).map(r=>r.x),state];
  // Overlay the projected trail and point so they remain locatable behind ridges.
  g.strokeStyle='#d5fff0';g.lineWidth=1.7;g.setLineDash([3,3]);g.beginPath();path.forEach((x,i)=>{const [px,py]=pointFor(x);i?g.lineTo(px,py):g.moveTo(px,py);});g.stroke();g.setLineDash([]);
  rows.slice(0,index+1).filter(row=>row.decision==='undo').forEach(row=>{const [px,py]=pointFor(row.x);g.strokeStyle='#cfabff';g.lineWidth=2;g.beginPath();g.arc(px,py,8,0,Math.PI*2);g.stroke();});
  const [dotX,dotY]=pointFor(state);g.shadowColor='#6fe2bd';g.shadowBlur=18;g.fillStyle='#a1ffe0';g.beginPath();g.arc(dotX,dotY,6,0,Math.PI*2);g.fill();g.shadowBlur=0;g.strokeStyle='#fff';g.lineWidth=2;g.stroke();
  g.fillStyle='#e5edf5';g.font='12px system-ui';g.fillText(`x${a}: ${state[a].toFixed(2)}   x${b}: ${state[b].toFixed(2)}   高度 ${terrainHeight(state,target).toFixed(3)}`,12,22);
  const origin=project(0,0,low-.1*span);
  for(const [u,v,label,color] of [[1,0,`x${a}`,'#ffbd8a'],[0,1,`x${b}`,'#91bfff']]){const end=project(u,v,low-.1*span);g.strokeStyle=color;g.beginPath();g.moveTo(origin[0],origin[1]);g.lineTo(end[0],end[1]);g.stroke();g.fillStyle=color;g.fillText(label,end[0]+5,end[1]-5);}
  g.fillStyle='#a7b8cc';g.fillText(`水平 ${((view.yaw*180/Math.PI%360+360)%360).toFixed(0)}° · 俯仰 ${(view.pitch*180/Math.PI).toFixed(0)}° · ${view.zoom.toFixed(2)}×`,12,h-12);
  el('frame').textContent=`第 ${t.toFixed(1)} / ${doc.steps.length} 轮${rows[index].decision==='undo'?' · ↶ 后悔撤销':''}`;
  el('slice-note').textContent='其余坐标：'+state.map((v,i)=>i===a||i===b?null:`x${i}=${v.toFixed(2)}`).filter(Boolean).join('，')+'。动画在相邻实测状态间插值。';
}

function drawProfile(g,w,h,doc,rows,index,state,t){
  const target=doc.target_evaluation_only,coords=rows.map(r=>r.x[0]);
  const lo=Math.min(-2,...coords.map(v=>v-.5),target[0]-1),hi=Math.max(2,...coords.map(v=>v+.5),target[0]+1);
  const samples=Array.from({length:241},(_,i)=>{const x=lo+(hi-lo)*i/240;return [x,terrainHeight([x],target)];});
  let bottom=Math.min(...samples.map(p=>p[1])),top=Math.max(...samples.map(p=>p[1]));const pad=Math.max(.5,(top-bottom)*.08);bottom-=pad;top+=pad;
  const px=x=>55+(x-lo)/(hi-lo)*(w-80),py=y=>35+(top-y)/(top-bottom)*(h-80);
  g.font='12px system-ui';g.fillStyle='#a7b8cc';
  for(let i=0;i<5;i++){const z=bottom+(top-bottom)*i/4;g.strokeStyle='#2a3848';g.beginPath();g.moveTo(55,py(z));g.lineTo(w-25,py(z));g.stroke();g.fillText(z.toFixed(1),3,py(z)+4);}
  g.strokeStyle='#7cafea';g.lineWidth=2;g.beginPath();samples.forEach(([x,z],i)=>i?g.lineTo(px(x),py(z)):g.moveTo(px(x),py(z)));g.stroke();
  g.setLineDash([4,4]);g.strokeStyle='#e7b66e';g.beginPath();g.moveTo(px(target[0]),30);g.lineTo(px(target[0]),h-40);g.stroke();g.setLineDash([]);
  g.fillStyle='#e7b66e';g.fillText('峰/谷位置（仅供评价）',Math.max(55,Math.min(w-170,px(target[0])+5)),25);
  g.strokeStyle='#6fe2bd';g.lineWidth=3;g.beginPath();[...rows.slice(0,index+1).map(r=>r.x),state].forEach((x,i)=>{const y=terrainHeight(x,target);i?g.lineTo(px(x[0]),py(y)):g.moveTo(px(x[0]),py(y));});g.stroke();
  g.fillStyle='#a1ffe0';g.beginPath();g.arc(px(state[0]),py(terrainHeight(state,target)),6,0,Math.PI*2);g.fill();
  g.fillStyle='#e5edf5';g.fillText(`x=${state[0].toFixed(3)}   高度=${terrainHeight(state,target).toFixed(3)}`,55,h-8);
  g.fillStyle='#a7b8cc';g.fillText(lo.toFixed(1),55,h-30);g.fillText(hi.toFixed(1),w-45,h-30);
  el('frame').textContent=`第 ${t.toFixed(1)} / ${doc.steps.length} 轮`;
  el('slice-note').textContent='这是原始一维函数剖面，未添加虚构的第二个坐标。峰/谷位置和函数公式仅供画图评价，不输入模型。';
}
document.addEventListener('DOMContentLoaded',initTerrain);
