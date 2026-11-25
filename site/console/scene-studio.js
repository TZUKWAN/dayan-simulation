/** Data-bound presentation system. Geometry is presentation; coordinates and values are archived model output. */
(function () {
  'use strict';
  const C = { blue: 0x72c9ed, teal: 0x67dec5, amber: 0xefbb79, purple: 0xb6a6ee,
    ink: 0x172837, slate: 0x344c5c, text: '#d8e9f1' };
  const colors = [C.teal, C.amber, C.purple, C.blue, 0xd99eac, 0x9dbcc4, 0xdacb92, 0x9eb2e6];
  const compartments = {
    S: { label: '易感群体', color: C.teal },
    E: { label: '潜伏群体', color: C.purple },
    I: { label: '感染群体', color: C.amber },
    R: { label: '移出群体', color: C.blue }
  };
  const sir = { title:'SIR 群体状态', keys:['S','I','R'],
    paths:[['S','I','感染'],['I','R','恢复移出']] };
  const compartmentModels = new Map([
    ['NET052', { title:'SIS 群体状态', keys:['S','I'], fraction:'I_frac',
      paths:[['S','I','感染'],['I','S','恢复后再易感']] }],
    ['NET053', sir],
    ['NET-SIR', sir],
    ['NET055', { title:'SEIR 群体状态', keys:['S','E','I','R'],
      paths:[['S','E','暴露'],['E','I','进入感染期'],['I','R','恢复移出']] }]
  ]);
  const pct = new Intl.NumberFormat('zh-CN',{style:'percent',minimumFractionDigits:1,maximumFractionDigits:2});

  // Group shares are measured or derived from the documented closed populations.
  function readCompartments(model, observed, population) {
    if (model.fraction) {
      const i = observed[model.fraction] ??
        (Number.isFinite(population) && population > 0 && Number.isFinite(observed.I) ? observed.I / population : NaN);
      if (!Number.isFinite(i) || i < 0 || i > 1) return null;
      const reference = observed.I_star;
      return { shares: { S:1-i, I:i }, reference: Number.isFinite(reference) && reference>=0 && reference<=1 ? reference : null };
    }
    const sizes = model.keys.map(key => observed[key]);
    if (sizes.some(size => !Number.isFinite(size) || size < 0)) return null;
    const total = sizes.reduce((sum,size) => sum + size, 0);
    if (!Number.isFinite(total) || total <= 0) return null;
    return { shares:Object.fromEntries(model.keys.map((key,index)=>[key,sizes[index]/total])), reference:null };
  }

  function compositionFor(modelId,frame,population){
    const model=compartmentModels.get(modelId);
    const reading=model&&readCompartments(model,frame?.aggregates||{},population);
    return reading?{...reading,title:model.title,paths:model.paths,nodes:model.keys.map(key=>({key,...compartments[key]}))}:null;
  }
  function positioned(entity){
    return entity.type!=='age_group'&&Number.isFinite(entity.x)&&Number.isFinite(entity.y);
  }
  function inSceneSpace(entity,frame) {
    if(frame?.population?.format!=='dayan-populations-v1')return true;
    const groups=frame.population.groups||[],group=groups.find(g=>g.id===entity.group);
    const units=[...new Set(groups.filter(g=>g.count&&g.units?.x&&g.units.x===g.units.y).map(g=>g.units.x))];
    const unit=frame.space?.unit||(units.length===1?units[0]:null);
    return Boolean(unit&&group?.units?.x===unit&&group?.units?.y===unit);
  }
  function resolve(stream) {
    const frames = stream.frames || [], first = frames[0] || {};
    const entities = (first.entities || []).filter(e=>inSceneSpace(e,first)), facilities = first.facilities || [];
    const definition = stream.manifest?.model_definition || {};
    const visual = definition.visualization || first.presentation?.visualization || first.presentation || {};
    const hasWorld = entities.some(positioned) || facilities.some(f=>
      ['road','road_network','model_facility','exit','counter'].includes(f.type));
    const kind = (stream.provenance !== 'entity' && first.population?.format!=='dayan-populations-v1') || !hasWorld ? 'observations'
      : facilities.some(f => f.type === 'road' && f.length) ? 'ring-road'
      : facilities.some(f => f.type === 'road_network') ? 'geographic'
      : entities.some(e => e.type === 'resident') ? 'lattice'
      : entities.some(e => ['server', 'customer'].includes(e.type)) ? 'queue'
      : 'spatial';
    const type = entities[0]?.type, scenario=definition.scenario||first.presentation?.scenario;
    const exercise=stream.model_id==='NET121';
    const glyph = ['person','vehicle','cell','point'].includes(visual.glyph) ? visual.glyph
      : ['car','bus'].includes(type) ? 'vehicle'
      : ['resident'].includes(type) ? 'cell'
      : ['pedestrian','customer','person'].includes(type) ? 'person' : 'point';
    const field = kind === 'ring-road' ? 'speed' : visual.color_by || definition.agents?.color_by || 'state';
    const values = new Set(); let lo = Infinity, hi = -Infinity;
    for (const frame of frames) for (const e of (frame.entities || [])) {
      const v = e[field];
      if (typeof v === 'number' && Number.isFinite(v)) { lo = Math.min(lo,v); hi = Math.max(hi,v); }
      if (v !== undefined && values.size < 64) values.add(String(v));
    }
    const categories = [...values].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
    const binary=!!categories.length&&categories.every(v=>v==='0'||v==='1')&&(visual.label||'').startsWith('是否');
    const actionColor=visual.action_by===field&&visual.action_poses;
    const continuous = !actionColor && Number.isFinite(lo) && (categories.length > 8 || !!visual.color_by);
    return { version: 1, kind, glyph, field, label: visual.label || (field === 'speed' ? '速度' : field),
      lo, hi, categories, continuous, binary, count: stream.n_entities_max || entities.length,
      rich: (stream.n_entities_max || entities.length) <= 220, scenario, visual, exercise,
      title: scenario?.title || (exercise?'景区步道应急演练':{ 'ring-road':'环形交通', geographic:'空间路网', lattice:'格点群体', queue:'服务队列 · 序位重建', spatial:'主体空间', observations:'汇总观测' }[kind]) };
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
  function label(parent,text,w=20,h=3,color=C.text,plaque=false) {
    const canvas=document.createElement('canvas');canvas.width=512;canvas.height=160;
    const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
    const sp=new THREE.Sprite(new THREE.SpriteMaterial({map:texture,transparent:true,depthWrite:false,depthTest:false}));sp.renderOrder=10;
    sp.scale.set(w,h,1);parent.add(sp);
    const draw=(lines)=>{const ctx=canvas.getContext('2d');ctx.clearRect(0,0,512,160);ctx.textAlign='center';
      if(plaque){
        ctx.fillStyle='rgba(16,30,38,.91)';
        ctx.beginPath();ctx.roundRect(18,12,476,lines.length>1?134:81,17);ctx.fill();
      }
      if(typeof lines==='string')lines=[lines];lines.forEach((line,i)=>{ctx.fillStyle=i===0?color:'#a8c1d0';let size=i===0?64:48;ctx.font=`500 ${size}px "Segoe UI", "Microsoft YaHei", sans-serif`;while(ctx.measureText(line).width>490&&size>16){size-=2;ctx.font=`500 ${size}px "Segoe UI", "Microsoft YaHei", sans-serif`;}ctx.fillText(line,256,65+i*62);});texture.needsUpdate=true;};
    draw(text);sp.userData.redraw=draw;sp.userData.sceneLayer='labels';return sp;
  }
  function scaleFor(frame){
    const bounds=frame.space?.bounds;
    return bounds?.length===4?70/Math.max(bounds[2]-bounds[0],bounds[3]-bounds[1],1e-9):1;
  }
  function resizeGround(stage,frame) {
    const ground=stage.userData.ground;
    if(!ground)return;
    const bounds=frame.space?.bounds;
    const worldScale=scaleFor(frame);
    const width=bounds?(bounds[2]-bounds[0])*worldScale:76;
    const depth=bounds?(bounds[3]-bounds[1])*worldScale:76;
    ground.deck.scale.set(width,1,depth);
    ground.seams.scale.set(width,1,depth);
    if(bounds)stage.userData.extent={width,depth};
  }
  function floorPlan(stage,frame) {
    const interior=frame.facilities?.some(f=>f.kind==='room'||f.kind==='building');
    const deck=mesh(stage,new THREE.BoxGeometry(1,.95,1),material(interior?0x748986:0x5c6d6e,{roughness:.92,metalness:.02}),0,-.53,0);
    const seams=new THREE.GridHelper(1,20,0x3e4f51,0x485c59);
    seams.position.y=-.04;
    seams.material.transparent=true;
    seams.material.opacity=.2;
    stage.add(seams);
    stage.userData.ground={deck,seams};
    resizeGround(stage,frame);
  }
  function stage(scene,profile,first) {
    // A display plinth is a visual reference, never a simulated geographic feature.
    scene.background=new THREE.Color(0x081420);scene.fog=new THREE.Fog(0x081420,100,280);
    const lights=new THREE.Group();scene.add(lights);
    lights.add(new THREE.HemisphereLight(0xd3e8ff,0x243549,2.2));
    const key=new THREE.DirectionalLight(0xffedd7,3.1);key.position.set(-26,55,30);key.castShadow=true;
    const shadowSize=profile.rich?2048:1024;
    key.shadow.mapSize.set(shadowSize,shadowSize);Object.assign(key.shadow.camera,{left:-48,right:48,top:48,bottom:-48,near:1,far:150});
    key.shadow.bias=-.00035;key.shadow.normalBias=.08;key.shadow.radius=3;lights.add(key);
    const rim=new THREE.DirectionalLight(0x86bcf2,1.9);rim.position.set(32,25,-32);lights.add(rim);
    const floor=mesh(scene,new THREE.PlaneGeometry(450,450),material(0x0c1b2c,{roughness:1,metalness:0}),0,-2.4,0);floor.rotation.x=-Math.PI/2;floor.userData.sceneLayer='base';
    const g=new THREE.Group();g.userData.isStudioStage=true;scene.add(g);
    if(profile.kind==='observations'){
      g.userData.extent={width:42,depth:26};
      const message=label(g,['本次运行只有汇总观测','趋势与状态流见分析区'],36,9);
      message.position.y=1;
      delete message.userData.sceneLayer;
      return g;
    }
    const circular=['ring-road','queue'].includes(profile.kind);
    if(circular){
      const radius=profile.kind==='queue'?18:37.4;g.userData.radius=radius+.8;
      mesh(g,new THREE.CylinderGeometry(radius,radius+.7,1.4,160),material(0x1e3445),0,-1.15,0);
      mesh(g,new THREE.CylinderGeometry(radius-.1,radius-.1,.18,160),material(0x294252,{roughness:.84}),0,-.35,0);
      ring(g,radius-.05,.07,-.22,0x81a8b9,.55);ring(g,radius+.2,.1,-1.55,0x64bfc4,.55);
      const geo=new THREE.BufferGeometry(),p=[];
      for(let i=0;i<120;i++){const a=i/120*Math.PI*2,r=radius-(i%5===0?1.9:1.3);p.push(Math.cos(a)*r,-.23,Math.sin(a)*r,Math.cos(a)*(radius-.8),-.23,Math.sin(a)*(radius-.8));}
      geo.setAttribute('position',new THREE.Float32BufferAttribute(p,3));g.add(new THREE.LineSegments(geo,new THREE.LineBasicMaterial({color:0x83a5b3,transparent:true,opacity:.32})));
    }else if(profile.kind==='geographic'){
      const grid=new THREE.GridHelper(220,55,0x537696,0x3b5871);
      grid.position.y=-.7;grid.material.transparent=true;grid.material.opacity=.27;g.add(grid);
    }else{
      floorPlan(g,first);
    }
    for(const part of g.children)part.userData.sceneLayer||='base';
    if(profile.kind==='ring-road'){
      const roadGroup=new THREE.Group();roadGroup.userData.sceneLayer='roads';g.add(roadGroup);
      mesh(roadGroup,new THREE.CylinderGeometry(32,32,.35,160),material(0x152733,{roughness:.92}),0,-.03,0);
      const road=mesh(roadGroup,new THREE.RingGeometry(28.3,31.7,192),material(0x45515b,{roughness:.94,side:THREE.DoubleSide}),0,.17,0);road.rotation.x=-Math.PI/2;
      ring(roadGroup,28.35,.065,.19,0xd0d7d2,.8);ring(roadGroup,31.65,.065,.19,0xd0d7d2,.8);
      ring(roadGroup,27.9,.1,.18,0x6b9399,.45);ring(roadGroup,32.05,.1,.18,0x6b9399,.45);
      // Road-edge dashes: no fictitious additional lane or intersection.
      const dashes=new THREE.InstancedMesh(new THREE.PlaneGeometry(.45,.11),new THREE.MeshBasicMaterial({color:0xb8c7cb,transparent:true,opacity:.6}),100),stamp=new THREE.Object3D();
      for(let i=0;i<100;i++){
        const a=i/100*Math.PI*2;
        stamp.position.set(Math.cos(a)*31.25,.195,Math.sin(a)*31.25);stamp.rotation.set(-Math.PI/2,0,-a-Math.PI/2);stamp.updateMatrix();dashes.setMatrixAt(i,stamp.matrix);
      }
      roadGroup.add(dashes);
      const length=first.facilities.find(f=>f.type==='road').length;
      [0,.25,.5,.75].forEach(f=>{const a=f*Math.PI*2,sp=label(roadGroup,String(Math.round(length*f)),4,1);sp.position.set(Math.cos(a)*34.1,.5,Math.sin(a)*34.1);});
    }
    return g;
  }
  function isPerson(ent,profile) {
    if(['pedestrian','customer','person'].includes(ent.type))return true;
    return profile.glyph==='person'&&!['server','car','bus','resident','age_group'].includes(ent.type);
  }
  const namedPoses=new Map([
    ['standing','idle'],['waiting','idle'],['arrived','idle'],
    ['walking','walk'],['running','run'],['seated','sit'],['fallen','down']
  ]);
  function personPose(ent,profile,moving) {
    const {action_by:field,action_poses:poses}=profile.visual||{};
    return (field&&poses?.[String(ent[field])])||namedPoses.get(ent.state)||(moving?'walk':'idle');
  }
  function peopleBatch(group,rich) {
    const root=new THREE.Object3D(), body=new THREE.Object3D(), parts=[];
    root.add(body);
    const skin=material(0xc3a08c,{roughness:.75,metalness:0});
    const fabric=material(0xffffff,{roughness:.82,metalness:0});
    const trousers=material(0x304654,{roughness:.92,metalness:0});
    const shoes=material(0x222e33,{roughness:.85,metalness:0});
    const hair=material(0x3e3733,{roughness:.9,metalness:0});
    function part(parent,geo,mat,x,y,z,tinted=false,pickable=false) {
      const stamp=new THREE.Object3D();
      stamp.position.set(x,y,z);
      parent.add(stamp);
      const instances=new THREE.InstancedMesh(geo,mat,3000);
      instances.count=0;
      instances.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      instances.frustumCulled=false;
      instances.boundingSphere=new THREE.Sphere(new THREE.Vector3(),520);
      instances.castShadow=rich;
      instances.userData.sceneLayer='entities';
      group.add(instances);
      parts.push({stamp,instances,tinted,pickable});
    }
    const joint=(parent,x,y)=>{
      const item=new THREE.Object3D();
      item.position.set(x,y,0);
      parent.add(item);
      return item;
    };
    part(body,rounded(.37,.5,.24,.042),fabric,0,.32,0,true,true);
    part(body,new THREE.BoxGeometry(.33,.16,.216),trousers,0,.03,0);
    part(body,new THREE.SphereGeometry(.124,10,8),skin,0,.691,.015);
    const cap=new THREE.SphereGeometry(.126,10,6,0,Math.PI*2,0,Math.PI*.53);
    part(body,cap,hair,0,.72,.005);
    const arms=[], legs=[];
    for(const side of [-1,1]){
      const shoulder=joint(body,side*.218,.46);
      part(shoulder,new THREE.CapsuleGeometry(.053,.175,3,6),fabric,0,-.119,0,true);
      const elbow=joint(shoulder,0,-.224);
      part(elbow,new THREE.CapsuleGeometry(.044,.147,3,6),skin,0,-.105,0);
      arms.push({shoulder,elbow});

      const hip=joint(body,side*.091,-.035);
      part(hip,new THREE.CapsuleGeometry(.066,.244,3,6),trousers,0,-.17,0);
      const knee=joint(hip,0,-.342);
      part(knee,new THREE.CapsuleGeometry(.054,.222,3,6),trousers,0,-.144,0);
      part(knee,new THREE.BoxGeometry(.112,.083,.215),shoes,0,-.33,.052);
      legs.push({hip,knee});
    }
    return {root,body,parts,arms,legs,shirt:new THREE.Color(),clothTone:new THREE.Color(0x728586)};
  }
  function drawPeople(batch,models,time,selected,reduced) {
    const {root,body,parts,arms,legs,shirt,clothTone}=batch;
    const ids=[];
    for(const model of models.values()){
      if(!model.userData.person||!model.visible)continue;
      const {entityId,pose,heading,size,phase,stateColor}=model.userData;
      const index=ids.push(entityId)-1;
      const walking=pose==='walk'||pose==='run',sitting=pose==='sit',down=pose==='down';
      const stride=walking&&!reduced?Math.sin(time*(pose==='run'?12:8)+phase):0;
      root.position.copy(model.position);
      root.rotation.y=heading;
      root.scale.setScalar(size);
      body.position.y=(down?.146:sitting?.47:.75)+Math.abs(stride)*.012;
      body.rotation.x=down?-Math.PI/2:pose==='run'?.13:0;
      for(let i=0;i<2;i++){
        const signed=(i===0?-1:1)*stride;
        legs[i].hip.rotation.x=sitting?-1.25:signed*(pose==='run'?.76:.53);
        legs[i].knee.rotation.x=sitting?1.21:Math.max(0,-signed)*.72;
        arms[i].shoulder.rotation.x=-signed*.55;
        arms[i].elbow.rotation.x=pose==='run'?-1.05:Math.min(0,signed*.3);
      }
      root.updateMatrixWorld(true);
      shirt.set(stateColor).lerp(clothTone,.43);
      if(String(entityId)===selected)shirt.setHex(0x86e0ce);
      for(const {stamp,instances,tinted} of parts){
        instances.setMatrixAt(index,stamp.matrixWorld);
        if(tinted)instances.setColorAt(index,shirt);
      }
    }
    for(const {instances,pickable} of parts){
      instances.count=ids.length;
      if(pickable)instances.userData.instanceIds=ids;
      instances.instanceMatrix.needsUpdate=true;
      if(instances.instanceColor)instances.instanceColor.needsUpdate=true;
    }
  }
  function entity(ent,profile) {
    if(ent.type==='server'){
      const m=new THREE.Mesh(rounded(1.5,1.6,1.3,.1),material(color(ent,profile)));m.castShadow=true;
      mesh(m,new THREE.BoxGeometry(1.05,.35,.04),material(0xb5dce5,{emissive:0x37777b,emissiveIntensity:.4}),0,.35,.68);return m;
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
    if(p.continuous)return [{color:C.teal,text:`${p.label} ${Number(p.lo.toPrecision(4))}`},{color:C.amber,text:Number(p.hi.toPrecision(4)).toString()}];
    if(!p.categories.length)return [{color:C.teal,text:'主体位置来自模型计算'}];
    if(p.field===p.visual?.action_by){
      const names={idle:'站立或等待',walk:'步行',run:'跑步',sit:'坐下',down:'卧倒'};
      return p.categories.slice(0,8).map((code,i)=>({color:colors[i],text:names[p.visual.action_poses[code]]||code}));
    }
    const states={evacuated:'已疏散',on_bus:'乘车中',outbound:'驶向安置点',pickup:'待接驳',preparing:'准备中',queue:'等候乘车',return:'返程',walking:'步行中',
      waiting:'停留',fallen:'倒地待助',seated:'就地协助',exited:'已离场'};
    return p.categories.slice(0,8).map((v,i)=>({color:colors[i],text:p.kind==='geographic'||p.exercise?(states[v]||v):v}));
  }
  function facility(spec) {
    const root=new THREE.Group();root.userData.facilityKind=spec.kind;
    const dark=material(0x294956,{roughness:.9});
    const parts=root.userData.parts={};
    const colors={room:0xb2a994,building:0xa89e90,road:0x36434b,exit:0x6d9881,source:0x608779,
      destination:0x6d9787,obstacle:0x747871,zone:0x526b67,service:0x857a68,signal:0x677983};
    parts.base=mesh(root,new THREE.BoxGeometry(1,1,1),material(colors[spec.kind]||0x697970,{roughness:.9,metalness:.02}));
    if(['room','building'].includes(spec.kind)){
      parts.walls=[];
      parts.seams=new THREE.GridHelper(1,14,0x938b77,0x9a927f);
      parts.seams.material.opacity=.18;
      parts.seams.material.transparent=true;
      root.add(parts.seams);
    }else if(['exit','source'].includes(spec.kind)){
      const frame=material(0x72ad8e,{roughness:.6});
      parts.posts=[0,1].map(()=>mesh(root,new THREE.BoxGeometry(1,1,1),frame));
      parts.beam=mesh(root,new THREE.BoxGeometry(1,1,1),frame);
    }else if(spec.kind==='signal'){
      parts.post=mesh(root,new THREE.CylinderGeometry(.08,.08,2.6,8),dark,0,1.3,0);
      parts.lamp=mesh(root,new THREE.SphereGeometry(.32,12,8),material(0xa6bec8),0,2.7,0);
    }
    parts.label=label(root,[],12.8,3.5,'#f0f5f4',true);return root;
  }
  function wallRuns(room,facilities) {
    const x0=room.x-room.width/2,x1=room.x+room.width/2;
    const y0=room.y-room.depth/2,y1=room.y+room.depth/2;
    const openings=facilities.filter(f=>['exit','source'].includes(f.kind));
    const edges=[['x',y0,x0,x1],['x',y1,x0,x1],['y',x0,y0,y1],['y',x1,y0,y1]];
    return edges.flatMap(([axis,at,lo,hi])=>{
      const across=axis==='x'?'y':'x',spanKey=axis==='x'?'width':'depth';
      const crossKey=axis==='x'?'depth':'width';
      const gaps=openings.filter(d=>Math.abs(d[across]-at)<=d[crossKey]/2+1e-7)
        .map(d=>[Math.max(lo,d[axis]-d[spanKey]/2),Math.min(hi,d[axis]+d[spanKey]/2)])
        .filter(([start,end])=>end>start).sort((a,b)=>a[0]-b[0]);
      const pieces=[];
      let edge=lo;
      for(const [start,end] of gaps){
        if(start>edge)pieces.push({axis,at,start:edge,end:start});
        edge=Math.max(edge,end);
      }
      if(hi>edge)pieces.push({axis,at,start:edge,end:hi});
      return pieces;
    });
  }
  function positionWalls(root,facility,frame,unit) {
    const walls=root.userData.parts.walls;
    const pieces=wallRuns(facility,frame.facilities||[]);
    pieces.forEach(({axis,at,start,end},i)=>{
      if(!walls[i]){
        walls[i]=mesh(root,new THREE.BoxGeometry(1,1,1),material(0xc2bfaf,{roughness:.84,metalness:.04}));
        walls[i].castShadow=true;
      }
      const wall=walls[i], mid=(start+end)/2, length=(end-start)*unit;
      const x=((axis==='x'?mid:at)-facility.x)*unit;
      const z=(facility.y-(axis==='x'?at:mid))*unit;
      const height=z>0?.45:THREE.MathUtils.clamp(1.65*unit,1.7,4.5);
      wall.visible=true;
      wall.position.set(x,height/2,z);
      wall.scale.set(axis==='x'?length:.19,height,axis==='y'?length:.19);
    });
    for(let i=pieces.length;i<walls.length;i++)walls[i].visible=false;
  }
  function updateFacility(root,f,fr,toWorld) {
    const [x,,z]=toWorld(f,fr);
    const unit=scaleFor(fr);
    const w=f.width*unit,d=f.depth*unit,p=root.userData.parts;
    root.position.set(x,.02+(Number.isFinite(f.z)?f.z*unit:0),z);
    const room=['room','building'].includes(f.kind);
    const floorMark=['destination','zone'].includes(f.kind);
    const baseHeight=f.kind==='obstacle'||f.kind==='service'?.95:room?.12:floorMark?.014:.075;
    p.base.scale.set(w,baseHeight,d);
    p.base.position.y=baseHeight/2+(floorMark?.115:-.01);
    p.base.castShadow=baseHeight>.2;
    if(p.seams){
      p.seams.position.y=baseHeight;
      p.seams.scale.set(w,1,d);
    }
    if(p.walls)positionWalls(root,f,fr,unit);
    if(p.posts){
      const alongX=w>=d,span=Math.max(w,d);
      const height=THREE.MathUtils.clamp(2.05*unit,2.45,5.2);
      p.posts.forEach((post,i)=>{post.scale.set(.28,height,.28);post.position.set(alongX?(i-.5)*span:0,height/2,alongX?0:(i-.5)*span);});
      p.beam.scale.set(alongX?span+.28:.28,.25,alongX?.28:span+.28);p.beam.position.set(0,height,0);
    }
    const tone=[0xa6bec8,0xe88e87,0xefbb79,0x67dec5][f.tone??0]||0xa6bec8;
    if(p.lamp)p.lamp.material.color.setHex(tone);
    p.label.position.set(0,room?2.7:3.25,room?-d/2:0);
    const caption=Number.isFinite(f.value)?'状态值 '+Number(f.value.toPrecision(5)):f.role==='context'?'场所参照':'';
    const mark=[f.label,caption].filter(Boolean);
    const key=mark.join('\n');
    if(key!==p.label.userData.caption){
      p.label.userData.caption=key;
      p.label.userData.redraw(mark);
    }
    root.userData.actualFacility={...f};
  }
  window.DAYAN_SCENE_STUDIO={resolve,inSceneSpace,compositionFor,stage,entity,color,legend,resizeGround,wallRuns,
    facility,updateFacility,isPerson,personPose,peopleBatch,drawPeople,scaleFor};
})();
