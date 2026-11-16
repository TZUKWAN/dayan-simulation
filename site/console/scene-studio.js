/** Data-bound presentation system. Geometry is presentation; coordinates and values are archived model output. */
(function () {
  'use strict';
  const C = { blue: 0x72c9ed, teal: 0x67dec5, amber: 0xefbb79, purple: 0xb6a6ee,
    ink: 0x172837, slate: 0x344c5c, text: '#d8e9f1' };
  const colors = [C.teal, C.amber, C.purple, C.blue, 0xd99eac, 0x9dbcc4, 0xdacb92, 0x9eb2e6];
  function resolve(stream) {
    const frames = stream.frames || [], first = frames[0] || {};
    const entities = first.entities || [], facilities = first.facilities || [];
    const definition = stream.manifest?.model_definition || {};
    const visual = definition.visualization || {};
    const kind = stream.provenance !== 'entity' ? 'indicators'
      : facilities.some(f => f.type === 'road' && f.length) ? 'ring-road'
      : facilities.some(f => f.type === 'road_network') ? 'geographic'
      : entities.some(e => e.type === 'resident') ? 'lattice'
      : entities.some(e => e.type === 'age_group') ? 'cohorts'
      : entities.some(e => ['server', 'customer'].includes(e.type)) ? 'queue'
      : 'spatial';
    const type = entities[0]?.type, scenario=definition.scenario;
    const glyph = ['person','vehicle','cell','point'].includes(visual.glyph) ? visual.glyph
      : ['car','bus'].includes(type) ? 'vehicle'
      : ['resident'].includes(type) ? 'cell'
      : ['pedestrian','customer'].includes(type) ? 'person' : 'point';
    const field = kind === 'ring-road' ? 'speed' : kind==='cohorts' ? 'I' : visual.color_by || definition.agents?.color_by || 'state';
    const values = new Set(); let lo = Infinity, hi = -Infinity;
    for (const frame of frames) for (const e of (frame.entities || []).slice(0,3000)) {
      const v = e[field];
      if (typeof v === 'number' && Number.isFinite(v)) { lo = Math.min(lo,v); hi = Math.max(hi,v); }
      if (v !== undefined && values.size < 64) values.add(String(v));
    }
    const categories = [...values].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
    const binary=!!categories.length&&categories.every(v=>v==='0'||v==='1')&&(visual.label||'').startsWith('是否');
    const continuous = Number.isFinite(lo) && (categories.length > 8 || !!visual.color_by || kind==='cohorts');
    return { version: 1, kind, glyph, field, label: visual.label || (field === 'speed' ? '速度' : field),
      lo, hi, categories, continuous, binary, count: stream.n_entities_max || entities.length,
      rich: (stream.n_entities_max || entities.length) <= 220, scenario,
      title: (scenario?.title?(/[0-9]/.test(scenario.title)?'底模 · ':'')+scenario.title:null) || { 'ring-road':'环形交通', geographic:'空间路网', lattice:'格点群体', queue:'服务队列 · 序位示意', spatial:'主体空间', cohorts:'分组仓室 · 柱高为 I', indicators:'指标演化' }[kind] };
  }
  function material(color, more={}) {
    return new THREE.MeshStandardMaterial({ color, roughness:.52, metalness:.22, envMapIntensity:.3, ...more });
  }
  function mesh(parent, geometry, mat, x=0,y=0,z=0) {
    const m = new THREE.Mesh(geometry,mat);m.position.set(x,y,z);m.receiveShadow=true;parent.add(m);return m;
  }
  function rounded(w,h,d,r=.08) {
    const s=new THREE.Shape(),x=-w/2,z=-d/2;
    s.moveTo(x+r,z);s.lineTo(x+w-r,z);s.quadraticCurveTo(x+w,z,x+w,z+r);
    s.lineTo(x+w,z+d-r);s.quadraticCurveTo(x+w,z+d,x+w-r,z+d);
    s.lineTo(x+r,z+d);s.quadraticCurveTo(x,z+d,x,z+d-r);
    s.lineTo(x,z+r);s.quadraticCurveTo(x,z,x+r,z);
    const g=new THREE.ExtrudeGeometry(s,{depth:Math.max(.01,h-2*r),bevelEnabled:true,bevelSegments:2,steps:1,bevelSize:r*.5,bevelThickness:r,curveSegments:3});
    g.rotateX(-Math.PI/2);g.center();return g;
  }
  function ring(parent,r,width,y,color,opacity=1) {
    const m=mesh(parent,new THREE.RingGeometry(r-width/2,r+width/2,160),new THREE.MeshBasicMaterial({color,transparent:opacity<1,opacity,side:THREE.DoubleSide,depthWrite:opacity===1}),0,y,0);
    m.rotation.x=-Math.PI/2;return m;
  }
  function label(parent,text,w=20,h=3,color=C.text) {
    const canvas=document.createElement('canvas');canvas.width=512;canvas.height=160;
    const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
    const sp=new THREE.Sprite(new THREE.SpriteMaterial({map:texture,transparent:true,depthWrite:false,depthTest:false}));sp.renderOrder=10;
    sp.scale.set(w,h,1);parent.add(sp);
    const draw=(lines)=>{const ctx=canvas.getContext('2d');ctx.clearRect(0,0,512,160);ctx.textAlign='center';
      if(typeof lines==='string')lines=[lines];lines.forEach((line,i)=>{ctx.fillStyle=i===0?color:'#a8c1d0';let size=i===0?64:48;ctx.font=`500 ${size}px "Segoe UI", "Microsoft YaHei", sans-serif`;while(ctx.measureText(line).width>490&&size>16){size-=2;ctx.font=`500 ${size}px "Segoe UI", "Microsoft YaHei", sans-serif`;}ctx.fillText(line,256,65+i*62);});texture.needsUpdate=true;};
    draw(text);sp.userData.redraw=draw;return sp;
  }
  function stage(scene,profile,first) {
    // A display plinth is a visual reference, never a simulated geographic feature.
    scene.background=new THREE.Color(0x101f2e);scene.fog=new THREE.Fog(0x101f2e,135,280);
    const lights=new THREE.Group();scene.add(lights);
    lights.add(new THREE.HemisphereLight(0xd3e8ff,0x243549,2.2));
    const key=new THREE.DirectionalLight(0xffedd7,3.1);key.position.set(-26,55,30);key.castShadow=true;
    key.shadow.mapSize.set(2048,2048);Object.assign(key.shadow.camera,{left:-48,right:48,top:48,bottom:-48,near:1,far:150});
    key.shadow.bias=-.00035;key.shadow.normalBias=.08;key.shadow.radius=3;lights.add(key);
    const rim=new THREE.DirectionalLight(0x86bcf2,1.9);rim.position.set(32,25,-32);lights.add(rim);
    const floor=mesh(scene,new THREE.PlaneGeometry(450,450),material(0x101f2e,{roughness:1,metalness:0}),0,-2.4,0);floor.rotation.x=-Math.PI/2;
    const g=new THREE.Group();g.userData.isStudioStage=true;scene.add(g);
    const circular=['ring-road','indicators','queue','cohorts'].includes(profile.kind);
    if(circular){
      const radius=profile.kind==='queue'?18:profile.kind==='cohorts'?22:profile.kind==='indicators'?32:37.4;g.userData.radius=radius+.8;
      mesh(g,new THREE.CylinderGeometry(radius,radius+.7,1.4,160),material(0x1e3445),0,-1.15,0);
      mesh(g,new THREE.CylinderGeometry(radius-.1,radius-.1,.18,160),material(0x294252,{roughness:.84}),0,-.35,0);
      ring(g,radius-.05,.07,-.22,0x81a8b9,.55);ring(g,radius+.2,.1,-1.55,0x64bfc4,.55);
      const geo=new THREE.BufferGeometry(),p=[];
      for(let i=0;i<120;i++){const a=i/120*Math.PI*2,r=radius-(i%5===0?1.9:1.3);p.push(Math.cos(a)*r,-.23,Math.sin(a)*r,Math.cos(a)*(radius-.8),-.23,Math.sin(a)*(radius-.8));}
      geo.setAttribute('position',new THREE.Float32BufferAttribute(p,3));g.add(new THREE.LineSegments(geo,new THREE.LineBasicMaterial({color:0x83a5b3,transparent:true,opacity:.32})));
    }else{
      mesh(g,rounded(77,1.6,77,.5),material(0x20394a),0,-1.1,0);
      mesh(g,rounded(76,.12,76,.25),material(0x2d4755,{roughness:.85}),0,-.24,0);
      const grid=new THREE.GridHelper(70,14,0x638595,0x638595);grid.position.y=-.16;grid.material.transparent=true;grid.material.opacity=.13;g.add(grid);
      const bounds=first.space?.bounds;
      if(bounds){const sp=label(g,[`${bounds[2]-bounds[0]} × ${bounds[3]-bounds[1]} ${first.space.unit||''}`,'模型空间 · 坐标等比映射'],26,4);sp.position.set(0,0,41);}
    }
    if(profile.kind==='ring-road'){
      mesh(g,new THREE.CylinderGeometry(32,32,.35,160),material(0x152733,{roughness:.92}),0,-.03,0);
      const road=mesh(g,new THREE.RingGeometry(28.3,31.7,192),material(0x45515b,{roughness:.94,side:THREE.DoubleSide}),0,.17,0);road.rotation.x=-Math.PI/2;
      ring(g,28.35,.065,.19,0xd0d7d2,.8);ring(g,31.65,.065,.19,0xd0d7d2,.8);
      ring(g,27.9,.1,.18,0x6b9399,.45);ring(g,32.05,.1,.18,0x6b9399,.45);
      // Road-edge dashes: no fictitious additional lane or intersection.
      const dashes=new THREE.InstancedMesh(new THREE.PlaneGeometry(.45,.11),new THREE.MeshBasicMaterial({color:0xb8c7cb,transparent:true,opacity:.6}),100),stamp=new THREE.Object3D();
      for(let i=0;i<100;i++){
        const a=i/100*Math.PI*2;
        stamp.position.set(Math.cos(a)*31.25,.195,Math.sin(a)*31.25);stamp.rotation.set(-Math.PI/2,0,-a-Math.PI/2);stamp.updateMatrix();dashes.setMatrixAt(i,stamp.matrix);
      }
      g.add(dashes);
      const length=first.facilities.find(f=>f.type==='road').length;
      [0,.25,.5,.75].forEach(f=>{const a=f*Math.PI*2,sp=label(g,String(Math.round(length*f)),4,1);sp.position.set(Math.cos(a)*34.1,.5,Math.sin(a)*34.1);});
      ring(g,21,.045,-.22,0x93b8c4,.16);ring(g,19.5,.04,-.22,0x93b8c4,.09);
      mesh(g,new THREE.CylinderGeometry(18.8,19.1,.45,128),material(0x233f50,{roughness:.65}),0,-.06,0);
      ring(g,18.75,.055,.18,0x7dbbc3,.55);ring(g,16.9,.08,.19,0x8196a0,.25);
      const dial=mesh(g,new THREE.RingGeometry(16.5,16.85,128),new THREE.MeshBasicMaterial({color:C.blue}),0,.21,0);dial.rotation.x=-Math.PI/2;
      const heading=label(g,['停 车 占 比','RING TRAFFIC · 环形交通'],20,4.6);heading.position.set(0,1,-10.5);
      const stats=label(g,'',26,8);stats.position.set(0,1,0);g.userData.stats=stats;g.userData.dial=dial;
    }
    return g;
  }
  function entity(ent,profile) {
    if(ent.type==='server'){
      const m=new THREE.Mesh(rounded(1.5,1.6,1.3,.1),material(color(ent,profile)));m.castShadow=true;
      mesh(m,new THREE.BoxGeometry(1.05,.35,.04),material(0xb5dce5,{emissive:0x37777b,emissiveIntensity:.4}),0,.35,.68);return m;
    }
    if(ent.type==='age_group'){
      const m=new THREE.Mesh(new THREE.CylinderGeometry(1.7,1.7,1,24),material(color(ent,profile)));
      m.userData.cohort=true;m.castShadow=true;
      const sp=label(m,'',9,2.8);m.userData.cohortLabel=sp;return m;
    }
    const glyph=['car','bus'].includes(ent.type)?'vehicle':ent.type==='resident'?'cell':['pedestrian','customer'].includes(ent.type)?'person':profile.glyph;
    const col=color(ent,profile);
    if(glyph==='vehicle'){
      // Root is the pickable body; details preserve the exact entity ID through ancestry.
      const body=new THREE.Mesh(rounded(ent.type==='bus'?2.5:1.55,.42,.85,.09),material(col));body.castShadow=true;
      if(profile.rich){
        mesh(body,rounded(.84,.36,.69,.1),material(0x9fc8d9,{roughness:.2,metalness:.5}),-.07,.27,0);
        mesh(body,rounded(.48,.03,.57,.035),material(col),-.1,.47,0).userData.stateColor=true;
        const wheels=new THREE.InstancedMesh(new THREE.CylinderGeometry(.16,.16,.11,10),material(0x14212b,{roughness:.95,metalness:0}),4),stamp=new THREE.Object3D();let index=0;
        [-.47,.47].forEach(x=>[-.43,.43].forEach(z=>{stamp.position.set(x,-.16,z);stamp.rotation.set(Math.PI/2,0,0);stamp.updateMatrix();wheels.setMatrixAt(index++,stamp.matrix);}));body.add(wheels);
        const lamps=new THREE.InstancedMesh(new THREE.BoxGeometry(.035,.09,.16),new THREE.MeshBasicMaterial({color:0xffffff}),4);index=0;stamp.rotation.set(0,0,0);
        [-.8,.8].forEach(x=>[-.25,.25].forEach(z=>{stamp.position.set(x,.03,z);stamp.updateMatrix();lamps.setMatrixAt(index,stamp.matrix);lamps.setColorAt(index++,new THREE.Color(x>0?0xf4eed9:0xdf806e));}));body.add(lamps);
      }
      body.userData.glyph='vehicle';return body;
    }
    if(glyph==='person'){
      const m=new THREE.Mesh(new THREE.CapsuleGeometry(.22,.48,3,8),material(col));m.castShadow=true;
      if(profile.rich){mesh(m,new THREE.SphereGeometry(.2,10,8),material(0xc2d7de),0,.65,0);}
      if(profile.kind==='queue')m.scale.setScalar(profile.count>20?.6:1);
      else if(profile.count<120)m.scale.setScalar(1.5);
      m.userData.glyph='person';return m;
    }
    if(glyph==='cell'){
      const m=new THREE.Mesh(rounded(.95,.72,.95,.07),material(col));m.castShadow=true;m.userData.glyph='cell';return m;
    }
    const radius=profile.count<100?.72:.47;
    const m=new THREE.Mesh(new THREE.SphereGeometry(radius,16,10),material(col,{roughness:.32}));m.castShadow=profile.rich;
    if(profile.rich){const base=mesh(m,new THREE.CylinderGeometry(radius*1.35,radius*1.35,.055,20),material(col,{roughness:.8}),0,-radius*.92,0);base.castShadow=false;}
    m.userData.glyph='point';return m;
  }
  function color(ent,p) {
    if(p.kind==='ring-road')return ent.speed===0?C.amber:C.blue;
    if(p.binary)return ent[p.field]===1?C.amber:C.teal;
    const v=ent[p.field];
    if(p.continuous&&typeof v==='number'&&Number.isFinite(v))return new THREE.Color(C.teal).lerp(new THREE.Color(C.amber),p.hi===p.lo?.5:THREE.MathUtils.clamp((v-p.lo)/(p.hi-p.lo),0,1));
    const i=p.categories.indexOf(String(v));return colors[(Math.max(0,i))%colors.length];
  }
  function legend(p) {
    if(p.kind==='ring-road')return [{color:C.blue,text:'行驶 · 速度 > 0'},{color:C.amber,text:'停车 · 速度 = 0'}];
    if(p.binary)return [{color:C.teal,text:p.label+'：否 (0)'},{color:C.amber,text:'是 (1)'}];
    if(p.kind==='indicators')return [{color:C.teal,text:'柱高：各指标 / 自身全程绝对峰值'},{color:C.amber,text:'汇总示意 · 非主体空间'}];
    if(p.continuous)return [{color:C.teal,text:`${p.label} ${Number(p.lo.toPrecision(4))}`},{color:C.amber,text:Number(p.hi.toPrecision(4)).toString()}];
    if(!p.categories.length)return [{color:C.teal,text:'主体位置来自模型计算'}];
    return p.categories.slice(0,8).map((v,i)=>({color:colors[i],text:`${p.label}: ${v}`}));
  }
  function indicator(group,name,index,count,stream) {
    const root=new THREE.Group(),col=colors[index%colors.length];
    const columns=Math.min(4,count),row=Math.floor(index/columns),column=index%columns;
    root.position.set((column-(columns-1)/2)*14,0,(row-(Math.ceil(count/columns)-1)/2)*18);
    mesh(root,rounded(9,.45,8,.2),material(0x3b5260),0,0,0);
    const bar=mesh(root,rounded(4.4,1,4.4,.1),material(col,{roughness:.35}),0,.5,0);
    const sp=label(root,'',18,5.6);sp.position.set(0,5,0);
    const peak=Math.max(1e-12,...stream.frames.map(f=>Math.abs(f.aggregates?.[name]||0)));
    root.userData={bar,label:sp,peak,name};group.add(root);return root;
  }
  function updateIndicator(root,value) {
    const {bar,label,peak,name}=root.userData,h=Math.max(.035,Math.abs(value)/peak*11);
    bar.scale.y=h;bar.position.y=h/2+.25;label.position.y=h+4.5;
    label.userData.redraw([name,String(Number(value.toPrecision(5)))+(value<0?' · 负值':'')]);
  }
  function updateStage(stage,fr,p) {
    if(stage.userData.stats){const entities=fr.entities||[],stopped=entities.filter(e=>e.speed===0).length;
      const ratio=entities.length?stopped/entities.length:0;
      stage.userData.stats.userData.redraw([`${(ratio*100).toFixed(1)}%`,`${stopped} / ${entities.length} 主体停车`]);
      const dial=stage.userData.dial;
      if(dial.userData.ratio!==ratio){dial.geometry.dispose();dial.geometry=new THREE.RingGeometry(16.5,16.85,128,1,Math.PI/2,Math.max(.001,ratio*Math.PI*2));dial.material.color.setHex(C.amber);dial.userData.ratio=ratio;}
    }
  }
  function facility(spec) {
    const root=new THREE.Group();root.userData.facilityKind=spec.kind;
    const pale=material(0xa6bec8,{roughness:.8}),dark=material(0x294956,{roughness:.9});
    const parts=root.userData.parts={};
    parts.base=mesh(root,new THREE.BoxGeometry(1,1,1),material(spec.kind==='road'?0x3c505d:0x426072,{roughness:.9}));
    if(['room','building'].includes(spec.kind)){
      parts.walls=Array.from({length:4},()=>mesh(root,new THREE.BoxGeometry(1,1,1),pale));
    }else if(['exit','destination','source'].includes(spec.kind)){
      parts.posts=[0,1].map(()=>mesh(root,new THREE.BoxGeometry(1,1,1),material(0x6dd7bb,{roughness:.4})));
      parts.beam=mesh(root,new THREE.BoxGeometry(1,1,1),material(0x9ee6d2));
    }else if(spec.kind==='signal'){
      parts.post=mesh(root,new THREE.CylinderGeometry(.08,.08,2.6,8),dark,0,1.3,0);
      parts.lamp=mesh(root,new THREE.SphereGeometry(.32,12,8),material(0xa6bec8),0,2.7,0);
    }
    parts.label=label(root,'',18,4.6);return root;
  }
  function updateFacility(root,f,fr,toWorld) {
    const [x,,z]=toWorld(f,fr),bounds=fr.space?.bounds;
    const unit=bounds?70/Math.max(bounds[2]-bounds[0],bounds[3]-bounds[1],1e-9):1;
    const w=f.width*unit,d=f.depth*unit,p=root.userData.parts;
    root.position.set(x,.02,z);
    const room=['room','building'].includes(f.kind);
    p.base.scale.set(w,f.kind==='obstacle'?.85:room?.1:.08,d);p.base.position.y=f.kind==='obstacle'?.425:0;
    if(p.walls){
      p.walls[0].scale.set(w,.75,.14);p.walls[0].position.set(0,.4,-d/2);
      p.walls[1].scale.set(w,.35,.14);p.walls[1].position.set(0,.2,d/2);
      p.walls[2].scale.set(.14,.75,d);p.walls[2].position.set(-w/2,.4,0);
      p.walls[3].scale.set(.14,.35,d);p.walls[3].position.set(w/2,.2,0);
    }
    if(p.posts){
      const alongX=w>=d,span=Math.max(w,d);
      p.posts.forEach((post,i)=>{post.scale.set(.22,2.4,.22);post.position.set(alongX?(i-.5)*span:0,1.2,alongX?0:(i-.5)*span);});
      p.beam.scale.set(alongX?span+.22:.22,.22,alongX?.22:span+.22);p.beam.position.set(0,2.45,0);
    }
    const tone=[0xa6bec8,0xe88e87,0xefbb79,0x67dec5][f.tone??0]||0xa6bec8;
    if(p.lamp)p.lamp.material.color.setHex(tone);
    p.label.position.set(0,room?2:3.8,room?-d/2:0);
    p.label.userData.redraw([f.label,Number.isFinite(f.value)?'状态值 '+Number(f.value.toPrecision(5)):f.role==='context'?'场所参照':'参与模型计算']);
    root.userData.actualFacility={...f};
  }
  window.DAYAN_SCENE_STUDIO={resolve,stage,entity,color,legend,indicator,updateIndicator,updateStage,facility,updateFacility};
})();
