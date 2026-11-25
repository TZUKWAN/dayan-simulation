/**
 * 大衍 DAYAN 3D 可视化引擎（Three.js）
 *
 * 两套体系：
 *  A. 族类场景（autoDetect）——无数据时的氛围场景
 *  B. 数据驱动真实世界（visualize）——每次仿真用观测数据现场构建 3D 场景：
 *     worldEpidemic   疫情/恐慌传染：城市街区 + 人群状态变色蔓延
 *     worldEvacuation 疏散逃生：房间 + 墙壁 + 出口 + 人群涌向出口
 *     worldCrowdPanic 集体恐慌：广场人群 + 参与度驱动的情绪爆发
 *     worldSegregation 居住分异：社区房屋 + 分异指数驱动的聚集
 *     worldTraffic    城市交通：街区路网 + 车流密度/通量驱动
 *     worldEconomy    宏观经济：工厂 + 通勤工人 + 工资/就业塔
 *     worldMarket     金融市场：交易大厅 + 全息行情柱
 *     worldNetwork    网络级联：节点球 + 脉冲传播
 *     worldSurface    通用数据地形：观测序列驱动的 3D 地貌
 */

(function () {
  'use strict';

  // ---- 场景注册表 ----
  const scenes = {};
  let currentScene = null;
  let renderer, camera, controls, container;
  let animationId = null;
  let clock = new THREE.Clock();
  let isRunning = true;
  const PLAY_DUR = 22;   // 所有世界场景统一的播放周期（秒），供侧栏图表同步

  // ---- 初始化 ----
  function init(containerId) {
    if (renderer) return; // 防重入：重复 init 会堆叠第二个画布
    container = document.getElementById(containerId);
    if (!container) return;
    container.style.overflow = 'hidden';

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(Math.max(1,container.clientWidth), Math.max(1,container.clientHeight));
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    // 电影级调色：ACES 色调映射让发光/夜色更有层次
    if (THREE.ACESFilmicToneMapping !== undefined) {
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.0;
    }
    container.appendChild(renderer.domElement);
    window._vizRenderer = renderer;   // 供审计检查 GPU 资源计数

    camera = new THREE.PerspectiveCamera(
      50,
      Math.max(1,container.clientWidth) / Math.max(1,container.clientHeight),
      0.1,
      1000
    );
    camera.position.set(15, 12, 15);
    camera.lookAt(0, 0, 0);

    setupControls();

    window.addEventListener('resize', onResize);
    // 容器尺寸变化（切页 display:none↔block、面板伸缩）也要恢复画布尺寸
    if (window.ResizeObserver) new ResizeObserver(() => onResize()).observe(container);
    buildEnvLighting();   // PMREM IBL：金属/玻璃的真实反射来源
    initPostFX();
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) stopAnimation();
      else {clock.start();scheduleAnimation();}
    });
    window.addEventListener('dayan:page', event => {
      if (event.detail === 'overview' || event.detail === 'replay') scheduleAnimation();
      else stopAnimation();
    });
    window.addEventListener('dayan:display', () => {
      if (container.checkVisibility()) {onResize();scheduleAnimation();}
      else stopAnimation();
    });
    scheduleAnimation();
  }

  let sceneObj = null;
  function getScene() {
    if (!sceneObj) {
      sceneObj = new THREE.Scene();
      sceneObj.background = new THREE.Color(0x8ab4dc);
      sceneObj.fog = new THREE.Fog(0x9ab8d8, 130, 330);   // 晴天大气（大城近景清晰，远景融进天色）
      if (window._envTex) sceneObj.environment = window._envTex;   // IBL 环境反射
      window._scene = sceneObj;
    }
    return sceneObj;
  }

  // ---- 3dviz 规范落地：IBL 环境 / 远景天际线 / 辉光纹理 ----
  function buildEnvLighting() {
    if (!renderer) return;
    try {
      const es = new THREE.Scene();
      es.add(new THREE.Mesh(new THREE.SphereGeometry(60, 16, 12),
        new THREE.MeshBasicMaterial({ color: 0x10233e, side: THREE.BackSide })));
      const gp = new THREE.Mesh(new THREE.CircleGeometry(60, 16),
        new THREE.MeshBasicMaterial({ color: 0x040a12 }));
      gp.rotation.x = -Math.PI / 2; gp.position.y = -0.01;
      es.add(gp);
      // 城市光带：青/紫/琥珀发光板环绕（反射出霓虹城市感）
      [[0x00e5ff, 10, 2, 0], [0xc084fc, -8, 5, 1.4], [0xffb74d, 6, -6, 2.8]].forEach(([cc, x, z, ry]) => {
        const b = new THREE.Mesh(new THREE.BoxGeometry(14, 3.5, 1),
          new THREE.MeshBasicMaterial({ color: cc }));
        b.position.set(x, 4 + ry, z); b.rotation.y = ry;
        es.add(b);
      });
      const pmrem = new THREE.PMREMGenerator(renderer);
      const rt = pmrem.fromScene(es, 0.06);
      pmrem.dispose();
      window._envTex = rt.texture;
      if (sceneObj) sceneObj.environment = rt.texture;
    } catch (e) { /* 环境反射失败不影响主渲染 */ }
  }

  // 远景天际线：雾中低细节剪影楼群（前/中/后景深分层）
  function addSkyline(scene, radius = 62, count = 42) {
    const geo = new THREE.BoxGeometry(1, 1, 1);
    const mat = new THREE.MeshBasicMaterial({ color: 0x0d2036 });
    const inst = new THREE.InstancedMesh(geo, mat, count);
    for (let i = 0; i < count; i++) {
      const ang = Math.random() * Math.PI * 2;
      const r = radius + Math.random() * 22;
      const w = 3 + Math.random() * 5, hh = 5 + Math.random() * Math.random() * 16;
      _tmpM.compose(
        new THREE.Vector3(Math.cos(ang) * r, hh / 2, Math.sin(ang) * r),
        _tmpQ.identity(),
        _tmpS.set(w, hh, w));
      inst.setMatrixAt(i, _tmpM);
    }
    _tmpS.set(1, 1, 1);
    scene.add(inst);
  }

  function makeGlowTexture(color = '#ffd98c') {
    const c = document.createElement('canvas');
    c.width = 64; c.height = 64;
    const g = c.getContext('2d');
    const gr = g.createRadialGradient(32, 32, 2, 32, 32, 32);
    gr.addColorStop(0, color); gr.addColorStop(0.35, color + '88');
    gr.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = gr; g.fillRect(0, 0, 64, 64);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
  }

  function addGlowSprite(scene, x, y, z, size, color, opacity = 0.5) {
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({
      map: makeGlowTexture(color), transparent: true, opacity,
      blending: THREE.AdditiveBlending, depthWrite: false }));
    sp.position.set(x, y, z);
    sp.scale.set(size, size, 1);
    scene.add(sp);
    return sp;
  }

  function setupControls() {
    let isDown = false, prevX = 0, prevY = 0, downX = 0, downY = 0;
    const dom = renderer.domElement;
    const pointer=new THREE.Vector2(),ray=new THREE.Raycaster();
    let lastHover=0;
    const pick=e=>{
      const st=window._vizStateStream;
      if(!st||st.preview||!sceneLayers.entities)return null;
      const rect=dom.getBoundingClientRect();
      if(!rect.width||!rect.height)return null;
      pointer.set((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1);
      ray.setFromCamera(pointer,camera);
      const group=getScene().children.find(c=>c.userData?.isStateGroup);
      const hit=ray.intersectObjects(group?.children.filter(m=>m.visible&&(m.userData.instanceIds||m.isMesh&&m.userData.entityId!==undefined))||[],true)[0];
      if(hit?.instanceId!==undefined&&hit.object.userData.instanceIds)return hit.object.userData.instanceIds[hit.instanceId];
      for(let object=hit?.object;object;object=object.parent)if(object.userData.entityId!==undefined)return object.userData.entityId;
      return null;
    };
    dom.addEventListener('pointerdown', e => {
      stopCameraMotion();
      paintHover(null);
      isDown = true; prevX = downX = e.clientX; prevY = downY = e.clientY;
      dom.setPointerCapture(e.pointerId);
    });
    dom.addEventListener('pointerup', e => {
      const clicked=isDown&&Math.hypot(e.clientX-downX,e.clientY-downY)<5;isDown=false;
      if(!clicked||e.button!==0)return;
      const entity=pick(e);if(entity!==null)selectStateEntity(String(entity),true);
    });
    dom.addEventListener('pointercancel',()=>{isDown=false;paintHover(null);});
    dom.addEventListener('lostpointercapture',()=>{isDown=false;});
    dom.addEventListener('pointerleave',()=>{paintHover(null);});
    dom.addEventListener('pointermove', e => {
      if (!isDown) {
        if(e.pointerType==='mouse'&&performance.now()-lastHover>85){lastHover=performance.now();paintHover(pick(e),e);}
        return;
      }
      const dx = e.clientX - prevX, dy = e.clientY - prevY;
      if(Math.hypot(e.clientX-downX,e.clientY-downY)>5&&stateCameraOverview){stateCameraOverview=false;reportPose();}
      if(followingStateEntity&&Math.hypot(e.clientX-downX,e.clientY-downY)>5){followingStateEntity='';document.dispatchEvent(new CustomEvent('dayan:camera-mode',{detail:{following:false}}));}
      prevX = e.clientX; prevY = e.clientY;
      if(window._vizStateStream){
        const orbit=new THREE.Spherical().setFromVector3(camera.position.clone().sub(viewTarget));
        orbit.theta-=dx*.006;
        orbit.phi=THREE.MathUtils.clamp(orbit.phi-dy*.006,.06,1.4);
        camera.position.setFromSpherical(orbit).add(viewTarget);
        camera.lookAt(viewTarget);
        if(!isRunning)renderer.render(getScene(),camera);
        return;
      }
      const angle = 0.005;
      const x = camera.position.x - 0, z = camera.position.z;
      const cos = Math.cos(angle * dx), sin = Math.sin(angle * dx);
      const nx = x * cos - z * sin, nz = x * sin + z * cos;
      camera.position.x = nx; camera.position.z = nz;
      camera.position.y = Math.max(2, camera.position.y - dy * 0.05);
      camera.lookAt(0, 0, 0);
      if(!isRunning) renderer.render(getScene(),camera);
    });
    dom.addEventListener('wheel', e => {
      stateCameraOverview=false;reportPose();
      e.preventDefault();
      if(window._vizStateStream){
        stopCameraMotion();
        const delta=camera.position.clone().sub(viewTarget);
        const distance=THREE.MathUtils.clamp(delta.length()*Math.exp(e.deltaY*.0015),4,viewFitRadius*10);
        camera.position.copy(viewTarget).add(delta.setLength(distance));
        camera.lookAt(viewTarget);
        if(!isRunning)renderer.render(getScene(),camera);
        return;
      }
      const dir = new THREE.Vector3();
      camera.getWorldDirection(dir);
      camera.position.addScaledVector(dir, e.deltaY * 0.02);
      camera.position.y = Math.max(2, camera.position.y);
      if(!isRunning) renderer.render(getScene(),camera);
    }, { passive: false });
  }

  function onResize() {
    if (!container) return;
    if (container.clientWidth < 10 || container.clientHeight < 10) return; // 页面隐藏时跳过，防 0 尺寸/NaN aspect
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    if(currentScene?.type?.startsWith('state_')&&stateCameraOverview)fitStateCamera();
    renderer.setSize(container.clientWidth, container.clientHeight);
    if (sceneObj && camera) renderer.render(sceneObj, camera);
  }

  // ---- 图层特效：风险热力 / 社会网络 / 人群流动（大屏图层按钮真实生效） ----
  let layerFxGroup = null;
  let layerFxMode = 'flow';

  function applyLayerFx(t) {
    const scene = getScene();
    // 扫除任何历史残留的 FX 组（只允许存在一个）
    for (const c of [...scene.children]) {
      if (c !== layerFxGroup && c.type === "Group" && c.userData && c.userData.isFx) {
        scene.remove(c);
        c.traverse(k => { if (k.geometry) k.geometry.dispose(); if (k.material) k.material.dispose(); });
      }
    }
    // clearScene() 会把 layerFxGroup 连同场景一起清掉 → 检测脱离并重新挂载
    if (!layerFxGroup || layerFxGroup.parent !== scene) {
      layerFxGroup = new THREE.Group();
      layerFxGroup.userData.isFx = true;
      scene.add(layerFxGroup);
    }
    layerFxGroup.userData.isFx = true;
    // 清空旧特效
    while (layerFxGroup.children.length) {
      const ch = layerFxGroup.children[0];
      layerFxGroup.remove(ch);
      if (ch.geometry) ch.geometry.dispose();
      if (ch.material) ch.material.dispose();
    }
    // 数据驱动的强度（取首个序列当前值）
    let intensity = 0.5;
    const vd = window._vizData;
    if (vd && vd.series.length) {
      const vals = vd.series[0];
      const lo = Math.min(...vals), hi = Math.max(...vals);
      const n = vals.length;
      const idx = Math.min(n - 1, Math.floor(((window._vizNow || 0) % PLAY_DUR) / PLAY_DUR * n));
      intensity = norm01(vals[idx], lo, hi);
    }
    if (layerFxMode === 'heat') {
      // 风险热力：红色脉冲地面环 + 红色点光
      const ring = new THREE.Mesh(new THREE.RingGeometry(2, 9 + intensity * 7, 48),
        new THREE.MeshBasicMaterial({ color: 0xff4d6d, transparent: true, opacity: 0.14 + intensity * 0.25, side: THREE.DoubleSide, depthWrite: false }));
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = 0.05;
      ring.scale.setScalar(1 + Math.sin(t * 2.2) * 0.05);
      layerFxGroup.add(ring);
      const glow = new THREE.PointLight(0xff4d6d, 0.5 + intensity * 1.2, 40);
      glow.position.y = 6;
      layerFxGroup.add(glow);
    } else if (layerFxMode === 'network') {
      // 社会网络：把人群按邻近关系连线
      const pos = window._vizAgentPos || [];
      const pts = [];
      const m = Math.min(pos.length, 90);
      for (let i = 0; i < m; i++) {
        if (!pos[i]) continue;
        let links = 0;
        for (let j = i + 1; j < m && links < 2; j++) {
          if (!pos[j]) continue;
          const dx = pos[i][0] - pos[j][0], dz = pos[i][1] - pos[j][1];
          if (dx * dx + dz * dz < 22) {
            pts.push(pos[i][0], 1.1, pos[i][1], pos[j][0], 1.1, pos[j][1]);
            links++;
          }
        }
      }
      if (pts.length) {
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pts), 3));
        layerFxGroup.add(new THREE.LineSegments(geo,
          new THREE.LineBasicMaterial({ color: 0x47e3d1, transparent: true, opacity: 0.4 })));
      }
    }
    // 群体筛选（通勤/高龄/学生）：非目标群体压暗
    const g = window._vizGroup;
    const crowd = window._vizCrowd;
    if (g != null && crowd && crowd.instanceColor) {
      for (let i = 0; i < crowd.count; i++) {
        _tmpC.set(i % 3 === g ? 0xffb74d : 0x2a3f4f);
        crowd.setColorAt(i, _tmpC);
      }
      crowd.instanceColor.needsUpdate = true;
    }
  }

  function setLayer(mode, render=true) {
    layerFxMode = mode || 'flow';
    if (render && window._vizStateStream && !window._vizStateStream.preview) {
      DAYAN3D.renderAt(window.DAYAN_RESULTS?.time || 0);
    }
  }
  function setGroupFilter(g) {
    window._vizGroup = (g === 'all' || g == null) ? null :
      { commute: 0, elder: 1, student: 2 }[g] ?? null;
  }

  function frame() {
    if (!isRunning) return;   // 暂停：冻结场景动画（侧栏时钟共用 _vizNow 同步停）
    const wallDt = clock.getDelta();
    const modelClock = window.DAYAN_RESULTS?.active ? window.DAYAN_RESULTS : null;
    const t = modelClock ? modelClock.time : clock.getElapsedTime();
    const dt = modelClock ? wallDt * modelClock.rate : wallDt;
    window._vizNow = t;   // 侧栏数据图表与 3D 动画共用此时钟
    if (currentScene && currentScene.update) currentScene.update(t, dt);
    if (window._vizStateStream && currentScene?.update!==vizStateUpdate) vizStateUpdate(t);
    if (!window._vizStateStream) applyLayerFx(t);
    // 天线红色闪灯
    blinkers.forEach((b, i) => {
      b.material.opacity = 0.3 + 0.7 * Math.abs(Math.sin(t * 2.1 + i * 1.7));
    });
    clouds.forEach(cl => {
      cl.sp.position.x += cl.v * 0.016;
      if (cl.sp.position.x > 95) cl.sp.position.x = -95;
    });
    updateWeather(dt);
    fxTick(dt, t);
    dayCycleTick(dt);
    introTick();
    renderFrame();
  }

  function scheduleAnimation() {
    if (animationId === null && isRunning && !document.hidden && container?.clientWidth) animationId=requestAnimationFrame(animate);
  }
  function stopAnimation() {
    if (animationId !== null) cancelAnimationFrame(animationId);
    animationId=null;
  }
  let frameCounter=0, rateSince=0;
  function animate(at) {
    animationId=null;
    frame();
    if (!rateSince) rateSince=at;
    frameCounter++;
    if (at-rateSince>=800) {
      const badge=document.getElementById('fps');
      if(badge)badge.textContent=Math.round(frameCounter*1000/(at-rateSince))+' fps';
      frameCounter=0;rateSince=at;
    }
    scheduleAnimation();
  }

  // ---- 通用工具 ----

  function disposeDeep(obj) {
    obj.shadow?.dispose?.();
    if (obj.isLight && obj.shadow) obj.shadow.dispose();
    if (obj.isInstancedMesh) obj.dispose();   // 释放 instanceMatrix/Color GPU 缓冲
    if (obj.geometry) obj.geometry.dispose();
    if (obj.material) {
      const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
      mats.forEach(m => {
        // CanvasTexture 等贴图单独释放（material.dispose 不覆盖 map）
        if (m.map) m.map.dispose();
        if (m.emissiveMap) m.emissiveMap.dispose();
        m.dispose();
      });
    }
    for (const c of [...obj.children]) disposeDeep(c);
    obj.children.length = 0;
  }

  function clearScene() {
    const scene = getScene();
    // 清掉全局引用，避免指向已释放对象的幽灵引用
    window._vizCrowd = null;
    window._vizAgentPos = null;
    window._vizStateStream = null;   // WP7：场景重建后状态流由 visualizeState 重挂
    document.getElementById('sceneLegend')?.remove();
    document.getElementById('vizStateHud')?.remove();
    blinkers = [];
    clouds = [];
    FXREG.halos.length=FXREG.trails.length=FXREG.waves.length=0;
    DAYCYCLE.lamps.length=DAYCYCLE.lights.length=0;
    if (weatherGroup) { weatherGroup = null; }   // 场景重建后由 visualize/setMood 重挂
    while (scene.children.length > 0) {
      const child = scene.children[0];
      scene.remove(child);
      disposeDeep(child);   // 递归：Group 嵌套的资源也必须释放（否则每次 visualize 泄漏~30 GPU 缓冲）
    }
    renderer?.renderLists.dispose();
  }

  function addLights(scene) {
    // 3dviz 规范：每盏光有职责——主光塑形/轮廓光分离剪影/环境补底
    window._vizLights = window._vizLights || {};
    const amb = new THREE.AmbientLight(0xb8c4d8, 0.5);
    scene.add(amb);
    window._vizLights.amb = amb;
    const hemi = new THREE.HemisphereLight(0x9ab8e0, 0x5a5a50, 0.75);
    scene.add(hemi);
    window._vizLights.hemi = hemi;
    // 主光：方位角 45° 仰角 55°，阴影相机贴合 ±26 受光区
    const key = new THREE.DirectionalLight(0xfff2e0, 1.7);
    key.position.set(18, 32, 10);
    window._vizLights.key = key;
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    const sc = key.shadow.camera;
    sc.left = -26; sc.right = 26; sc.top = 26; sc.bottom = -26;
    sc.near = 1; sc.far = 70;
    scene.add(key);
    // 轮廓光：背后紫光分离建筑剪影
    const rim = new THREE.DirectionalLight(0x9a6aff, 0.4);
    rim.position.set(-9, 12, -15);
    scene.add(rim);
    const pt = new THREE.PointLight(0xc084fc, 0.35, 80);
    pt.position.set(0, 18, 0);
    scene.add(pt);
    const pt2 = new THREE.PointLight(0xff8a5a, 0.25, 50);
    pt2.position.set(-10, 8, -10);
    scene.add(pt2);
  }

  let blinkers = [];   // 天线红色闪灯（clearScene 复位，frame 循环驱动）

  // ---- 沙盘环境情绪系统：LLM 从用户描述推断 → setMood 驱动天空/雾/光照/天气粒子/主题色调 ----
  const MOODS = {
    day:   { dome: ['#2a5aa8', '#6a9ad8', '#aac8e8'], fog: [0x9ab8d8, 130, 330], bg: 0x8ab4dc,
             key: [0xfff2e0, 1.7], hemi: [0x9ab8e0, 0x5a5a50, 0.75], amb: 0.5, exposure: 1.0, weather: null },
    dusk:  { dome: ['#3a2470', '#c05a8a', '#ff9a5a'], fog: [0xc4849a, 90, 280], bg: 0xc05a8a,
             key: [0xffc890, 1.1], hemi: [0xffb0a0, 0x5a4a7a, 0.7], amb: 0.7, exposure: 1.05, weather: null },
    night: { dome: ['#0a1030', '#14204a', '#1a2a5a'], fog: [0x101a34, 60, 240], bg: 0x0c1430,
             key: [0x8ab0e0, 0.55], hemi: [0x2a3a6a, 0x0a1020, 0.5], amb: 0.3, exposure: 0.92,
             weather: null },
    rain:  { dome: ['#3a4a5c', '#5a6a7c', '#7a8a9a'], fog: [0x6a7a8a, 60, 220], bg: 0x5a6a7c,
             key: [0xa0b8cc, 0.75], hemi: [0x6a7a8a, 0x2a323c, 0.7], amb: 0.55, exposure: 0.95,
             weather: 'rain' },
    snow:  { dome: ['#8aa2c0', '#b8c8dc', '#e8eef4'], fog: [0xd8e2ea, 70, 260], bg: 0xd8e2ea,
             key: [0xe8f0ff, 1.0], hemi: [0xc8d8e8, 0x8a9aa8, 0.8], amb: 0.6, exposure: 1.0,
             weather: 'snow' },
  };
  window._vizMood = 'day';
  window._vizTheme = 'modern';
  window._vizDensity = 0.7;

  // 主题 → 楼群调色板（makeBuildings / 城市街区取色）
  const THEMES = {
    modern: [0xd96c4f, 0x3aa6a0, 0xe0b45c, 0xe87a8a, 0x5a8ad0, 0x9a6ac0, 0xd8cfc0, 0xc9beb0],
    scifi:  [0x1a3a6a, 0x0d4a5a, 0x2a1a6a, 0x0a6a7a, 0x3a1a5a, 0x0a8a9a, 0x1a2a4a, 0x0a3a5a],
    ancient:[0x8a6a4a, 0xa08a5a, 0x6a5a3a, 0x9a8a6a, 0x7a5a3a, 0xa08a7a, 0x8a8a6a, 0x6a6a4a],
    suburb: [0x7aa870, 0x8ab070, 0xd0c090, 0x9ab87a, 0xc0b090, 0x8aa07a, 0xb8c8a0, 0xd0c8a8],
  };
  function themePalette() {
    return THEMES[window._vizTheme] || THEMES.modern;
  }

  let weatherGroup = null;   // 雨/雪粒子组（setMood 管理）

  function attachWeather(scene) {
    const cfg = (MOODS[window._vizMood] || MOODS.day);
    const want = cfg.weather;
    const has = weatherGroup && weatherGroup.parent === scene;
    if (want === 'rain' && !has) { setMood('rain', window._vizDensity); }
    else if (want === 'snow' && !has) { setMood('snow', window._vizDensity); }
  }

  function setMood(moodName, density) {
    window._vizDayCycle = false;   // 显式选定时段 → 固定光照
    const cfg = MOODS[moodName] || MOODS.day;
    window._vizMood = MOODS[moodName] ? moodName : 'day';
    window._vizDensity = (typeof density === 'number') ? Math.max(0.25, Math.min(1, density)) : 0.7;
    // 立即生效：雾 / 背景 / 曝光 / 灯光强度
    if (sceneObj) {
      sceneObj.fog = new THREE.Fog(cfg.fog[0], cfg.fog[1], cfg.fog[2]);
      sceneObj.background = new THREE.Color(cfg.bg);
    }
    if (renderer) renderer.toneMappingExposure = cfg.exposure;
    if (window._vizLights) {
      const { key, hemi, amb } = window._vizLights;
      key.color.set(cfg.key[0]); key.intensity = cfg.key[1];
      hemi.color.set(cfg.hemi[0]); hemi.groundColor.set(cfg.hemi[1]); hemi.intensity = cfg.hemi[2];
      if (amb) amb.intensity = cfg.amb;
    }
    // 天穹渐变：直接重建现有穹顶贴图
    const dome = sceneObj && sceneObj.children.find(c => c.geometry && c.geometry.type === 'SphereGeometry' && c.material && c.material.map);
    if (dome && dome.material.map) {
      const c2 = document.createElement('canvas');
      c2.width = 4; c2.height = 256;
      const g2 = c2.getContext('2d');
      const gr2 = g2.createLinearGradient(0, 0, 0, 256);
      gr2.addColorStop(0, cfg.dome[0]); gr2.addColorStop(0.58, cfg.dome[1]); gr2.addColorStop(1, cfg.dome[2]);
      g2.fillStyle = gr2; g2.fillRect(0, 0, 4, 256);
      dome.material.map.image = c2;
      dome.material.map.needsUpdate = true;
    }
    // 天气粒子（雨/雪）挂当前场景
    const scene = getScene();
    if (weatherGroup && weatherGroup.parent) weatherGroup.parent.remove(weatherGroup);
    weatherGroup = null;
    if (cfg.weather === 'rain') {
      weatherGroup = new THREE.Group();
      weatherGroup.userData.isWeather = true;
      const N = 380;
      const pos = new Float32Array(N * 6);
      for (let i = 0; i < N; i++) {
        const x = (Math.random() - 0.5) * 80, y = Math.random() * 34, z = (Math.random() - 0.5) * 80;
        pos[i * 6] = x; pos[i * 6 + 1] = y; pos[i * 6 + 2] = z;
        pos[i * 6 + 3] = x + 0.05; pos[i * 6 + 4] = y - 0.7; pos[i * 6 + 5] = z;
      }
      const wgeo = new THREE.BufferGeometry();
      wgeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      const wlines = new THREE.LineSegments(wgeo,
        new THREE.LineBasicMaterial({ color: 0x9ab8d0, transparent: true, opacity: 0.34 }));
      weatherGroup.add(wlines);
      weatherGroup.userData.rain = wgeo;
      scene.add(weatherGroup);
    } else if (cfg.weather === 'snow') {
      weatherGroup = new THREE.Group();
      weatherGroup.userData.isWeather = true;
      const N = 260;
      const pos = new Float32Array(N * 3);
      for (let i = 0; i < N; i++) {
        pos[i * 3] = (Math.random() - 0.5) * 80;
        pos[i * 3 + 1] = Math.random() * 34;
        pos[i * 3 + 2] = (Math.random() - 0.5) * 80;
      }
      const sgeo = new THREE.BufferGeometry();
      sgeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      const snow = new THREE.Points(sgeo, new THREE.PointsMaterial({
        color: 0xffffff, size: 0.22, transparent: true, opacity: 0.85,
        map: makeGlowTexture('#ffffff'), depthWrite: false }));
      weatherGroup.add(snow);
      weatherGroup.userData.snow = sgeo;
      scene.add(weatherGroup);
    }
  }

  // frame 循环驱动天气粒子
  function updateWeather(dt) {
    if (!weatherGroup || !weatherGroup.parent) return;
    if (weatherGroup.userData.rain) {
      const pos = weatherGroup.userData.rain.attributes.position.array;
      for (let i = 0; i < pos.length; i += 6) {
        const dy = 1.35 * dt * 60 * 0.016;
        pos[i + 1] -= dy; pos[i + 4] -= dy;
        if (pos[i + 1] < 0) { const d = 34 - pos[i + 1]; pos[i + 1] += d; pos[i + 4] += d; }
      }
      weatherGroup.userData.rain.attributes.position.needsUpdate = true;
    }
    if (weatherGroup.userData.snow) {
      const pos = weatherGroup.userData.snow.attributes.position.array;
      const t = clock.getElapsedTime();
      for (let i = 0; i < pos.length; i += 3) {
        pos[i + 1] -= 0.045;
        pos[i] += Math.sin(t * 1.3 + i) * 0.012;
        if (pos[i + 1] < 0) pos[i + 1] = 34;
      }
      weatherGroup.userData.snow.attributes.position.needsUpdate = true;
    }
  }

  // 主题密度 → 建筑生成参数（城市街区跳过率）
  function densitySkipRate() { return 0.1 + (1 - window._vizDensity) * 0.45; }

  // 渐变夜空穹顶（BackSide 大球，不受雾影响）
  function addSkyDome(scene, top, mid, bottom) {
    const MC = (MOODS[window._vizMood] || MOODS.day).dome;
    top = top || MC[0]; mid = mid || MC[1]; bottom = bottom || MC[2];
    const c = document.createElement('canvas');
    c.width = 4; c.height = 256;
    const g = c.getContext('2d');
    const grad = g.createLinearGradient(0, 0, 0, 256);
    grad.addColorStop(0, top); grad.addColorStop(0.58, mid); grad.addColorStop(1, bottom);
    g.fillStyle = grad; g.fillRect(0, 0, 4, 256);
    const tex = new THREE.CanvasTexture(c);
    const dome = new THREE.Mesh(
      new THREE.SphereGeometry(140, 24, 16),
      new THREE.MeshBasicMaterial({ map: tex, side: THREE.BackSide, fog: false, depthWrite: false }));
    dome.renderOrder = -1;
    scene.add(dome);
  }

  // 程序化立面纹理：墙色 + 窗框内凹 + 楼层线 + 玻璃天空反射梯度 + 少量亮灯
  // （真实航拍立面的核心：窗有"深度感"，墙有材质色）
  function shadeHex(hex, f) {
    const c = new THREE.Color(hex);
    c.r = Math.min(1, c.r * f); c.g = Math.min(1, c.g * f); c.b = Math.min(1, c.b * f);
    return '#' + c.getHexString();
  }
  function makeWindowTexture(cols = 8, rows = 16, density = 0.5, wallHex = '#cfc8ba') {
    const cell = 16, cw = cols * cell, ch = rows * cell;
    const c = document.createElement('canvas');
    c.width = cw; c.height = ch;
    const g = c.getContext('2d');
    // 墙体底色（轻微上下渐变，模拟光影）
    const wg = g.createLinearGradient(0, 0, 0, ch);
    wg.addColorStop(0, shadeHex(wallHex, 1.06));
    wg.addColorStop(1, shadeHex(wallHex, 0.88));
    g.fillStyle = wg; g.fillRect(0, 0, cw, ch);
    // 楼层线（每行之间深色分隔）
    g.fillStyle = shadeHex(wallHex, 0.62);
    for (let r2 = 0; r2 <= rows; r2++) g.fillRect(0, r2 * cell - 1, cw, 2);
    // 底层商铺带（最下一行）：大开间橱窗 + 彩色遮阳棚
    const awnCols = ['#c05a4a', '#3a8a7a', '#c0903a', '#5a6ac0'];
    for (let q = 0; q < cols; q++) {
      const x0 = q * cell;
      g.fillStyle = shadeHex(wallHex, 0.45);
      g.fillRect(x0 + 1, ch - cell + 2, cell - 2, cell - 6);
      const gr2 = g.createLinearGradient(0, ch - cell + 6, 0, ch - 6);
      gr2.addColorStop(0, '#3a4a5c'); gr2.addColorStop(1, '#6a8aa4');
      g.fillStyle = gr2;
      g.fillRect(x0 + 2, ch - cell + 8, cell - 4, cell - 12);
      g.fillStyle = awnCols[q % awnCols.length];
      g.fillRect(x0 + 1, ch - cell + 4, cell - 2, 3);
    }
    // 每格：窗框（深墙色）→ 玻璃（天空反射梯度）→ 顶部内凹阴影 → 底部窗台高光 → 少量暖光
    for (let r2 = 0; r2 < rows - 1; r2++) {
      for (let q = 0; q < cols; q++) {
        const x0 = q * cell, y0 = r2 * cell;
        g.fillStyle = shadeHex(wallHex, 0.55);            // 窗框
        g.fillRect(x0 + 1, y0 + 2, cell - 2, cell - 6);
        const lit = Math.random() < density * 0.28;
        const gr = g.createLinearGradient(0, y0 + 4, 0, y0 + cell - 6);
        if (lit) { gr.addColorStop(0, '#ffe2a0'); gr.addColorStop(1, '#e8a860'); }
        else { gr.addColorStop(0, '#c8e2f2'); gr.addColorStop(0.45, '#8ab4d0'); gr.addColorStop(1, '#6a92b0'); }
        g.fillStyle = gr;
        g.fillRect(x0 + 3, y0 + 5, cell - 7, cell - 11);
        g.fillStyle = 'rgba(0,0,0,0.30)';                 // 顶部内凹阴影
        g.fillRect(x0 + 3, y0 + 5, cell - 7, 3);
        g.fillStyle = 'rgba(255,255,255,0.28)';           // 窗台高光
        g.fillRect(x0 + 3, y0 + cell - 9, cell - 7, 1.6);
        if (Math.random() < 0.12) {                        // 半开窗/窗帘变化
          g.fillStyle = 'rgba(40,60,80,0.45)';
          g.fillRect(x0 + 3, y0 + 5 + Math.random() * (cell - 16), cell - 7, 5);
        }
      }
    }
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = 4;
    return tex;
  }

  // 道路：深色路面 + 白色虚线中线
  function addRoad(scene, x, z, w, l, horizontal) {
    const roadGeo = horizontal ? new THREE.PlaneGeometry(l, w) : new THREE.PlaneGeometry(w, l);
    const road = new THREE.Mesh(roadGeo,
      new THREE.MeshStandardMaterial({ color: 0x333a44, roughness: 0.85, metalness: 0.1 }));
    road.rotation.x = -Math.PI / 2;
    road.position.set(x, 0.01, z);
    road.receiveShadow = true;
    scene.add(road);
    // 虚线中线（InstancedMesh 合批：大城路网虚线数百个，单 mesh 逐个画会爆 draw call）
    const dashMat = new THREE.MeshBasicMaterial({ color: 0x9ab4c4, transparent: true, opacity: 0.45 });
    const nDash = Math.floor(l / 6);
    if (nDash > 0) {
      const dashGeo = horizontal ? new THREE.PlaneGeometry(1.2, 0.16) : new THREE.PlaneGeometry(0.16, 1.2);
      const inst = new THREE.InstancedMesh(dashGeo, dashMat, nDash);
      for (let i = 0; i < nDash; i++) {
        const off = -l / 2 + 3 + i * 6;
        _tmpV.set(horizontal ? off : x, 0.02, horizontal ? z : off);
        _tmpQ.identity();
        _tmpM.compose(_tmpV, _tmpQ, _tmpS.set(1, 1, 1));
        inst.setMatrixAt(i, _tmpM);
      }
      scene.add(inst);
    }
  }

  // 路灯：灯杆 + 暖光头 + 光锥（additive 假体积光）
  function addStreetLamps(scene, spots, lightsEvery = 1) {
    const group = new THREE.Group();
    (spots || []).forEach(([x, z], idx) => {
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.07, 2.6, 6),
        new THREE.MeshStandardMaterial({ color: 0x1c3040, roughness: 0.6, metalness: 0.5 }));
      pole.position.set(x, 1.3, z);
      group.add(pole);
      const head = new THREE.Mesh(new THREE.SphereGeometry(0.14, 8, 8),
        new THREE.MeshBasicMaterial({ color: 0xffd98c }));
      head.position.set(x, 2.7, z);
      group.add(head);
      // 辉光 sprite（3dviz：发光体要有辉光，值回成本）
      const glowSp = new THREE.Sprite(new THREE.SpriteMaterial({
        map: makeGlowTexture('#ffd98c'), transparent: true, opacity: 0.4,
        blending: THREE.AdditiveBlending, depthWrite: false }));
      glowSp.position.set(x, 2.7, z);
      glowSp.scale.set(1.6, 1.6, 1);
      group.add(glowSp);
      const cone = new THREE.Mesh(new THREE.ConeGeometry(1.1, 2.8, 12, 1, true),
        new THREE.MeshBasicMaterial({ color: 0xffd98c, transparent: true, opacity: 0.07,
          blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
      cone.position.set(x, 1.4, z);
      group.add(cone);
      if (idx % lightsEvery === 0) {          // 点光源限流：大城只给近处路口
        const glow = new THREE.PointLight(0xffd98c, 0.45, 7);
        glow.position.set(x, 2.6, z);
        group.add(glow);
      }
    });
    scene.add(group);
    return group;
  }

  // 行道树：干 + 双层锥冠
  // 女儿墙：屋顶四周凸沿（航拍视角下真实建筑的标志性细节）
  function addParapet(scene, x, y, z, w, d, color = 0x8a8478) {
    const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.8 });
    const t = 0.14, hgt = 0.22;
    [[0, -d / 2 + t / 2, w, t], [0, d / 2 - t / 2, w, t],
     [-w / 2 + t / 2, 0, t, d - 2 * t], [w / 2 - t / 2, 0, t, d - 2 * t]].forEach(([ox, oz, sw, sd]) => {
      const seg = new THREE.Mesh(new THREE.BoxGeometry(sw, hgt, sd), mat);
      seg.position.set(x + ox, y + hgt / 2, z + oz);
      scene.add(seg);
    });
  }

  // 人行道：道路两侧凸沿浅色混凝土板
  function addSidewalks(scene, x, z, w, l, horizontal) {
    const mat = new THREE.MeshStandardMaterial({ color: 0x8a8f98, roughness: 0.9 });
    const sw = 1.1, hgt = 0.07;
    for (const side of [-1, 1]) {
      const walk = new THREE.Mesh(new THREE.BoxGeometry(horizontal ? l : sw, hgt, horizontal ? sw : l), mat);
      walk.position.set(horizontal ? x : x + side * (w / 2 + sw / 2), hgt / 2, horizontal ? z + side * (w / 2 + sw / 2) : z);
      walk.receiveShadow = true;
      scene.add(walk);
    }
  }

  // 斑马线：路口白色条纹
  function addCrosswalk(scene, x, z, roadW) {
    const mat = new THREE.MeshBasicMaterial({ color: 0xd8dde4, transparent: true, opacity: 0.75 });
    for (let i = 0; i < 6; i++) {
      const off = -roadW / 2 + 0.5 + i * (roadW - 1) / 6;
      for (const dir of [-1, 1]) {
        const stripe = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 0.5), mat);
        stripe.rotation.x = -Math.PI / 2;
        stripe.position.set(x + off, 0.03, z + dir * (roadW / 2 + 0.8));
        scene.add(stripe);
        const stripe2 = new THREE.Mesh(new THREE.PlaneGeometry(0.5, 1.6), mat);
        stripe2.rotation.x = -Math.PI / 2;
        stripe2.position.set(x + dir * (roadW / 2 + 0.8), 0.03, z + off);
        scene.add(stripe2);
      }
    }
  }

  function addTrees(scene, spots) {
    const n = spots.length;
    if (!n) return;
    const trunkGeo = new THREE.CylinderGeometry(0.08, 0.12, 0.9, 6);
    const blobGeo = new THREE.IcosahedronGeometry(0.62, 1);
    const trunkMat = new THREE.MeshStandardMaterial({ color: 0x6a4a30, roughness: 0.9 });
    const blobMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.8, flatShading: true });
    const trunks = new THREE.InstancedMesh(trunkGeo, trunkMat, n);
    const blobs1 = new THREE.InstancedMesh(blobGeo, blobMat, n);
    const blobs2 = new THREE.InstancedMesh(blobGeo, blobMat, n);
    trunks.castShadow = true;
    const cols = [0x4a9a5a, 0x5ab84a, 0x3a8a6a, 0x6aa84a];
    spots.forEach(([x, z], i) => {
      const s2 = 0.7 + ((i * 37) % 10) / 14;
      _tmpV.set(x, 0.45 * s2, z); _tmpQ.identity(); _tmpS.set(s2, s2, s2);
      _tmpM.compose(_tmpV, _tmpQ, _tmpS);
      trunks.setMatrixAt(i, _tmpM);
      _tmpV.set(x, 1.25 * s2, z);
      _tmpM.compose(_tmpV, _tmpQ, _tmpS);
      blobs1.setMatrixAt(i, _tmpM);
      _tmpV.set(x + 0.18 * s2, 1.72 * s2, z - 0.1 * s2);
      _tmpS.setScalar(s2 * 0.68);
      _tmpM.compose(_tmpV, _tmpQ, _tmpS);
      blobs2.setMatrixAt(i, _tmpM);
      const cc = new THREE.Color(cols[i % cols.length]);
      blobs1.setColorAt(i, cc);
      blobs2.setColorAt(i, cc.clone().multiplyScalar(1.12));
    });
    blobs1.instanceColor.needsUpdate = true;
    blobs2.instanceColor.needsUpdate = true;
    _tmpS.set(1, 1, 1);
    scene.add(trunks, blobs1, blobs2);
  }

  // 柔和云朵（高空漂移）  // 柔和云朵（高空漂移）
  let clouds = [];
  function addClouds(scene, n = 7) {
    for (let i = 0; i < n; i++) {
      const sp = new THREE.Sprite(new THREE.SpriteMaterial({
        map: makeGlowTexture('#ffffff'), transparent: true, opacity: 0.32 + Math.random() * 0.2,
        depthWrite: false }));
      const ang = Math.random() * Math.PI * 2, r = 30 + Math.random() * 45;
      sp.position.set(Math.cos(ang) * r, 34 + Math.random() * 12, Math.sin(ang) * r);
      const w = 12 + Math.random() * 14;
      sp.scale.set(w, w * 0.45, 1);
      scene.add(sp);
      clouds.push({ sp, v: 0.25 + Math.random() * 0.35 });
    }
  }

  function addGround(scene, size = 40, color, sky = true) {
    if (!color) color = window._vizMood === 'snow' ? 0xd8e2ea : window._vizMood === 'night' ? 0x2a3644 : 0x5a6470;
    if(sky)addSkyDome(scene);
    // 地面微噪纹理（深浅斑块，去塑料感）
    const gc = document.createElement('canvas');
    gc.width = 128; gc.height = 128;
    const gg = gc.getContext('2d');
    gg.fillStyle = '#4e5864'; gg.fillRect(0, 0, 128, 128);
    for (let i = 0; i < 260; i++) {
      gg.fillStyle = Math.random() > 0.5 ? 'rgba(90,100,112,0.25)' : 'rgba(50,58,66,0.28)';
      gg.beginPath();
      gg.arc(Math.random() * 128, Math.random() * 128, 1 + Math.random() * 4, 0, 7);
      gg.fill();
    }
    const gtex = new THREE.CanvasTexture(gc);
    gtex.colorSpace = THREE.SRGBColorSpace;
    gtex.wrapS = gtex.wrapT = THREE.RepeatWrapping;
    gtex.repeat.set(Math.max(3, Math.round(size / 14)), Math.max(3, Math.round(size / 14)));
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(size, size),
      new THREE.MeshStandardMaterial({ color, roughness: 0.88, metalness: 0.15, map: gtex })
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.02;
    ground.receiveShadow = true;
    scene.add(ground);
  }

  function orbitCamera(t, r, h, speed = 0.1, lookY = 1) {
    const ang = t * speed;
    camera.position.x = Math.sin(ang) * r;
    camera.position.z = Math.cos(ang) * r;
    camera.position.y = h + Math.sin(t * 0.18) * 1.5;
    camera.lookAt(0, lookY, 0);
  }

  // 人群个体（胶囊体 + 头），InstancedMesh
  function makeCrowd(n, color) {
    const geo = new THREE.CapsuleGeometry(0.16, 0.42, 3, 8);
    const mat = new THREE.MeshStandardMaterial({ roughness: 0.6, metalness: 0.1 });
    const mesh = new THREE.InstancedMesh(geo, mat, n);
    mesh.castShadow = true;
    const c = new THREE.Color(color);
    for (let i = 0; i < n; i++) mesh.setColorAt(i, c);
    mesh.instanceColor.needsUpdate = true;
    window._vizCrowd = mesh;          // 供图层/群体筛选特效定位人群
    window._vizAgentPos = [];
    return mesh;
  }

  const _tmpM = new THREE.Matrix4();
  const _tmpV = new THREE.Vector3();
  const _tmpQ = new THREE.Quaternion();
  const _tmpS = new THREE.Vector3(1, 1, 1);
  const _tmpC = new THREE.Color();
  const _Y_AXIS = new THREE.Vector3(0, 1, 0);   // 复用：避免每主体每帧分配

  function setAgent(mesh, i, x, y, z, ry, scale, color) {
    _tmpV.set(x, y, z);
    _tmpQ.setFromAxisAngle(_Y_AXIS, ry || 0);
    _tmpS.setScalar(scale || 1);
    _tmpM.compose(_tmpV, _tmpQ, _tmpS);
    mesh.setMatrixAt(i, _tmpM);
    if (color !== undefined) {
      _tmpC.set(color);
      mesh.setColorAt(i, _tmpC);
    }
    if (mesh === window._vizCrowd) window._vizAgentPos[i] = [x, z];
  }

  function makeBuildings(scene, n, area, hMin, hMax, palette) {
    const group = new THREE.Group();
    const paletteArr = palette || [0xd8cfc0, 0xc9beb0, 0x8aa0b8, 0xb88a7a, 0x9ab0a0, 0xd9d4c8, 0xb0a898];
    // 3dviz 物质身份规范 + 彩色低多边形：饱和色 + flatShading + 暖窗
    const kind = () => {
      const r = Math.random();
      return r < 0.22 ? 'glass' : r < 0.78 ? 'windows' : 'concrete';
    };
    for (let i = 0; i < n; i++) {
      const w = 0.9 + Math.random() * 1.8, d = 0.9 + Math.random() * 1.8;
      const h = hMin + Math.random() * (hMax - hMin);
      const x = (Math.random() - 0.5) * area, z = (Math.random() - 0.5) * area;
      const kk = kind();
      const tex = makeWindowTexture(Math.max(3, Math.round(w * 3)), Math.max(6, Math.round(h * 3)),
        kk === 'glass' ? 0.16 : 0.35 + Math.random() * 0.35);
      let mat;
      if (kk === 'glass') {
        // 玻璃幕墙塔：青蓝彩色 + IBL 反射 + 稀疏亮窗
        mat = new THREE.MeshPhysicalMaterial({
          color: 0x4a7aa8, metalness: 0.55, roughness: 0.28,
          envMapIntensity: 1.3, flatShading: true,
          emissive: 0xffe8b0, emissiveIntensity: 0.18, emissiveMap: tex,
        });
      } else if (kk === 'concrete') {
        mat = new THREE.MeshStandardMaterial({
          color: paletteArr[i % paletteArr.length], roughness: 0.82, metalness: 0.04,
          flatShading: true,
          emissive: 0xffe8b0, emissiveIntensity: 0.12, emissiveMap: tex,
        });
      } else {
        mat = new THREE.MeshStandardMaterial({
          color: paletteArr[i % paletteArr.length], roughness: 0.62, metalness: 0.06,
          flatShading: true,
          emissive: 0xffe8b0, emissiveIntensity: 0.16, emissiveMap: tex,
        });
      }
      const geo = new THREE.BoxGeometry(w, h, d);
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(x, h / 2, z);
      mesh.castShadow = true; mesh.receiveShadow = true;
      group.add(mesh);
      // 高楼退台（剪影层次）
      if (h > (hMin + hMax) * 0.55 && Math.random() > 0.4) {
        const w2 = w * 0.62, d2 = d * 0.62, h2 = h * 0.28;
        const tex2 = makeWindowTexture(Math.max(3, Math.round(w2 * 3)), 8, 0.4);
        const top = new THREE.Mesh(new THREE.BoxGeometry(w2, h2, d2),
          kk === 'glass' ? new THREE.MeshPhysicalMaterial({
            color: 0x3a9ad0, metalness: 0.5, roughness: 0.3, envMapIntensity: 1.2, flatShading: true,
            emissive: 0xffdd99, emissiveIntensity: 0.3, emissiveMap: tex2 })
          : new THREE.MeshStandardMaterial({
            color: paletteArr[(i + 1) % paletteArr.length], roughness: 0.6, metalness: 0.08,
            flatShading: true,
            emissive: 0xffdd99, emissiveIntensity: 0.28, emissiveMap: tex2 }));
        top.position.set(x, h + h2 / 2, z);
        top.castShadow = true;
        group.add(top);
      }
      // 中低楼阳台薄板（建筑厚度感）
      if (h < (hMin + hMax) * 0.6 && Math.random() > 0.5) {
        const nBal = 2 + Math.floor(Math.random() * 3);
        for (let b = 0; b < nBal; b++) {
          const slab = new THREE.Mesh(new THREE.BoxGeometry(w * 1.06, 0.05, d * 0.3),
            new THREE.MeshStandardMaterial({ color: 0x2a4258, roughness: 0.6, metalness: 0.3 }));
          slab.position.set(x, h * (0.3 + b / nBal * 0.6), z + d / 2);
          group.add(slab);
        }
      }
      // 屋顶附件：水塔（25%）/ 空调机组（40%）
      const roofRnd = Math.random();
      if (roofRnd < 0.25 && h > 2) {
        const wt = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 0.5, 8),
          new THREE.MeshStandardMaterial({ color: 0x3a4a5a, roughness: 0.6, metalness: 0.3 }));
        wt.position.set(x + (Math.random() - 0.5) * w * 0.4, h + 0.25, z + (Math.random() - 0.5) * d * 0.4);
        group.add(wt);
        const wtCone = new THREE.Mesh(new THREE.ConeGeometry(0.24, 0.2, 8),
          new THREE.MeshStandardMaterial({ color: 0x2a3a48, roughness: 0.6 }));
        wtCone.position.set(wt.position.x, h + 0.58, wt.position.z);
        group.add(wtCone);
      } else if (roofRnd < 0.65) {
        for (let a = 0; a < 2; a++) {
          const ac = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.18, 0.24),
            new THREE.MeshStandardMaterial({ color: 0x4a5a6a, roughness: 0.5, metalness: 0.4 }));
          ac.position.set(x + (Math.random() - 0.5) * w * 0.5, h + 0.09, z + (Math.random() - 0.5) * d * 0.5);
          group.add(ac);
        }
      }
      // 高楼天线 + 红色闪灯
      if (h > (hMin + hMax) * 0.62) {
        const ant = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.05, 1.1, 5),
          new THREE.MeshStandardMaterial({ color: 0x2a3c50, roughness: 0.5, metalness: 0.6 }));
        ant.position.set(x, h + 0.55, z);
        group.add(ant);
        const tip = new THREE.Mesh(new THREE.SphereGeometry(0.09, 6, 6),
          new THREE.MeshBasicMaterial({ color: 0xff3355, transparent: true, opacity: 0.9 }));
        tip.position.set(x, h + 1.15, z);
        group.add(tip);
        blinkers.push(tip);
        // 塔顶辉光 sprite（3dviz：发光体要有辉光）
        addGlowSprite(group, x, h + 1.15, z, 1.1, '#ff3355', 0.35);
      }
    }
    scene.add(group);    scene.add(group);
    return group;
  }

  function makeHud() {
    let hud = document.getElementById('viz3dHud');
    if (!hud) {
      hud = document.createElement('div');
      hud.id = 'viz3dHud';
      hud.style.cssText = 'position:absolute;left:12px;top:10px;z-index:5;' +
        'font:11px monospace;color:#8fd8e8;background:rgba(6,14,26,.72);' +
        'border:1px solid rgba(0,229,255,.3);border-radius:6px;padding:7px 10px;' +
        'pointer-events:none;line-height:1.7;text-shadow:0 0 6px rgba(0,229,255,.4)';
      if (container) container.appendChild(hud);
    }
    return hud;
  }

  // 提取数值序列（剔除统计后缀与常量）
  function extractSeries(observations) {
    if (!observations || observations.length < 2) return { names: [], series: [] };
    const skip = /_min$|_max$|_std$|_mean$/;
    const cand = [];
    for (const k of Object.keys(observations[0])) {
      if (skip.test(k)) continue;
      let ok = true, vals = [];
      for (const o of observations) {
        const v = o[k];
        if (typeof v !== 'number' || !isFinite(v)) { ok = false; break; }
        vals.push(v);
      }
      if (!ok) continue;
      const lo = Math.min(...vals), hi = Math.max(...vals);
      if (hi - lo < 1e-12) continue;
      cand.push({ name: k, vals, lo, hi });
    }
    cand.sort((a, b) => a.name.localeCompare(b.name));
    return { names: cand.map(c => c.name), series: cand.map(c => c.vals) };
  }

  function norm01(v, lo, hi) { return (v - lo) / Math.max(hi - lo, 1e-12); }

  /* ============================================================
   * 数据驱动真实世界场景
   * ============================================================ */

  // ---- 疫情/恐慌传染：彩色城市街区 + 人群变色蔓延 ----
  function worldEpidemic(meta, seriesByName) {
    clearScene();
    const scene = getScene();
    addLights(scene);
    addGround(scene, 56, 0x0a1a2e);
    // 彩色楼群：青/紫/琥珀三族，亮窗纹理
    const fracS0 = seriesByName('I_frac') || seriesByName('I') || seriesByName(seriesByName._first);
    makeBuildings(scene, 26, 44, 1.8, 7, [0x1a5a7a, 0x5a2a8a, 0x2a6a4a, 0x8a4a2a]);
    addSkyline(scene, 56, 40);
    addStreetLamps(scene, [[4, 4], [-4, -4], [10, -6], [-8, 8], [0, 14], [-14, 0]]);
    addTrees(scene, [[7, -3], [-6, 6], [12, 4], [-11, -7], [3, 12], [-3, -13], [15, 9], [-16, 3]]);
    addRoad(scene, 0, 0, 2.2, 56, true);
    addRoad(scene, 0, 0, 2.2, 56, false);

    const fracS = fracS0;
    const n = fracS ? fracS.vals.length : 2;
    const fracLo = fracS ? Math.min(...fracS.vals) : 0, fracHi = fracS ? Math.max(...fracS.vals) : 1;

    const AG = Math.round(120 + 140 * (window._vizDensity || 0.7));
    const crowd = makeCrowd(AG, 0x00e5ff);
    scene.add(crowd);
    const agents = [];
    for (let i = 0; i < AG; i++) {
      agents.push({
        x: (Math.random() - 0.5) * 34, z: (Math.random() - 0.5) * 34,
        vx: (Math.random() - 0.5) * 0.02, vz: (Math.random() - 0.5) * 0.02,
        ph: Math.random() * 6,
      });
    }
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(6, 6.35, 64),
      new THREE.MeshBasicMaterial({ color: 0xff4d6d, transparent: true, opacity: 0.25, side: THREE.DoubleSide })
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.03;
    scene.add(ring);

    const CYAN = 0x00e5ff, RED = 0xff4d6d, AMBER = 0xffb74d;
    const hud = makeHud();
    const DUR = PLAY_DUR;
    const updateFn = (t) => {
      const idx = Math.min(n - 1, Math.floor((t % DUR) / DUR * n));
      const frac = fracS ? norm01(fracS.vals[idx], fracLo, fracHi) : 0.3;
      const kInf = Math.round(frac * AG);
      for (let i = 0; i < AG; i++) {
        const a = agents[i];
        a.x += a.vx * (1 + frac * 2.2); a.z += a.vz * (1 + frac * 2.2);
        if (Math.abs(a.x) > 17) a.vx *= -1;
        if (Math.abs(a.z) > 17) a.vz *= -1;
        const infected = i < kInf;
        const bob = infected ? Math.abs(Math.sin(t * 7 + a.ph)) * 0.22 : Math.sin(t * 1.6 + a.ph) * 0.05;
        setAgent(crowd, i, a.x, 0.55 + bob, a.z, Math.atan2(a.vx, a.vz),
                 infected ? 1.12 : 1, infected ? (i % 7 === 0 ? AMBER : RED) : CYAN);
      }
      crowd.instanceMatrix.needsUpdate = true;
      if (crowd.instanceColor) crowd.instanceColor.needsUpdate = true;
      ring.scale.setScalar(1 + frac * 1.6);
      ring.material.opacity = 0.12 + frac * 0.4;
      orbitCamera(t, 30, 30, 0.05);
      if (hud && fracS) hud.innerHTML =
        `<b style="color:#ffb74d">${meta.modelId}</b> · 情绪传染蔓延<br>` +
        `<span style="color:#ff4d6d">感染/恐慌比例 ${(fracS.vals[idx] * 100).toFixed(1)}%</span><br>` +
        `人群 ${AG} 体 · 感染 ${kInf} 体 · tick ${idx + 1}/${n}` +
        (meta.note ? `<br><span style="color:#5a7a8b">${meta.note.slice(0, 38)}</span>` : '');
    };
    return { update: updateFn, type: 'world-epidemic' };
  }

  // ---- 疏散逃生：精致房间 + 出口灯牌 + 顶灯光带 ----
  function worldEvacuation(meta, seriesByName) {
    clearScene();
    const scene = getScene();
    addLights(scene);
    const W = 22, D = 15, H = 4, wallT = 0.4, exitW = 3.4;
    // 棋盘格地板（canvas 纹理）
    const fc = document.createElement('canvas');
    fc.width = 128; fc.height = 128;
    const fg = fc.getContext('2d');
    for (let i = 0; i < 8; i++) for (let j = 0; j < 8; j++) {
      fg.fillStyle = (i + j) % 2 ? '#12233a' : '#0d1e33';
      fg.fillRect(i * 16, j * 16, 16, 16);
    }
    const floorTex = new THREE.CanvasTexture(fc);
    floorTex.colorSpace = THREE.SRGBColorSpace;
    floorTex.wrapS = floorTex.wrapT = THREE.RepeatWrapping;
    floorTex.repeat.set(3, 2);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(W, D),
      new THREE.MeshStandardMaterial({ map: floorTex, roughness: 0.7, metalness: 0.15 }));
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    scene.add(floor);
    const wallMat = new THREE.MeshStandardMaterial({ color: 0x1e3d5c, roughness: 0.55, metalness: 0.3, emissive: 0x16406a, emissiveIntensity: 0.35 });
    const mkWall = (w, h, d, x, y, z) => {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), wallMat);
      m.position.set(x, y, z); m.castShadow = true; scene.add(m);
    };
    mkWall(W, H, wallT, 0, H / 2, -D / 2);
    mkWall(wallT, H, D, -W / 2, H / 2, 0);
    mkWall(wallT, H, D, W / 2, H / 2, 0);
    const segW = (W - exitW) / 2;
    mkWall(segW, H, wallT, -(exitW + segW) / 2, H / 2, D / 2);
    mkWall(segW, H, wallT, (exitW + segW) / 2, H / 2, D / 2);
    // 墙沿发光腰线（彩色饰条）
    const trimMat = new THREE.MeshBasicMaterial({ color: 0x2ad0e8, transparent: true, opacity: 0.5 });
    [[0, -D / 2 + wallT / 2 + 0.01, W, 0.06], [-W / 2 + wallT / 2, 0, D, 0], [W / 2 - wallT / 2, 0, D, 0]].forEach(([x, z, len]) => {
      const trim = new THREE.Mesh(new THREE.BoxGeometry(x === 0 ? len : 0.06, 0.08, x === 0 ? 0.06 : len), trimMat);
      trim.position.set(x, H * 0.78, z);
      scene.add(trim);
    });
    // 顶灯光带（三条彩色发光板）
    const stripCols = [0x9fe8ff, 0xc0a8ff, 0x9fe8ff];
    stripCols.forEach((cc, i) => {
      const strip = new THREE.Mesh(new THREE.BoxGeometry(W * 0.7, 0.06, 0.5),
        new THREE.MeshBasicMaterial({ color: cc, transparent: true, opacity: 0.75 }));
      strip.position.set(0, H - 0.12, -D / 3 + i * (D / 3));
      scene.add(strip);
    });
    // 出口绿光门 + EXIT 灯牌
    const door = new THREE.Mesh(new THREE.PlaneGeometry(exitW, H * 0.8),
      new THREE.MeshBasicMaterial({ color: 0x00ffa3, transparent: true, opacity: 0.35, side: THREE.DoubleSide }));
    door.position.set(0, H * 0.4, D / 2);
    scene.add(door);
    const doorGlow = new THREE.PointLight(0x00ffa3, 1.2, 12);
    doorGlow.position.set(0, 2, D / 2 - 1);
    scene.add(doorGlow);
    const sc = document.createElement('canvas');
    sc.width = 128; sc.height = 48;
    const sg = sc.getContext('2d');
    sg.fillStyle = '#00382a'; sg.fillRect(0, 0, 128, 48);
    sg.fillStyle = '#00ffa3'; sg.font = 'bold 22px monospace';
    sg.textAlign = 'center'; sg.textBaseline = 'middle';
    sg.fillText('EXIT 出口', 64, 24);
    const signTex = new THREE.CanvasTexture(sc);
    signTex.colorSpace = THREE.SRGBColorSpace;
    const sign = new THREE.Mesh(new THREE.BoxGeometry(2.4, 0.8, 0.12),
      new THREE.MeshBasicMaterial({ map: signTex, transparent: true, opacity: 0.95 }));
    sign.position.set(0, H - 0.55, D / 2 - 0.35);
    scene.add(sign);
    addGlowSprite(scene, 0, H - 0.55, D / 2 - 0.2, 2.2, '#00ffa3', 0.4);

    const evacS = seriesByName('evacuated');
    const aliveS = seriesByName('alive');
    const sepS = seriesByName('min_separation');
    const n = evacS ? evacS.vals.length : (aliveS ? aliveS.vals.length : 2);
    const total = evacS ? Math.max(...evacS.vals) : (aliveS ? Math.max(...aliveS.vals) : 30);
    const AG = Math.min(60, Math.max(20, Math.round(total))) || 30;

    const crowd = makeCrowd(AG, 0x47e3d1);
    scene.add(crowd);
    const agents = [];
    for (let i = 0; i < AG; i++) {
      agents.push({ x: (Math.random() - 0.5) * (W - 3), z: (Math.random() - 0.5) * (D - 3), out: false, ph: Math.random() * 6 });
    }
    const hud = makeHud();
    const DUR = PLAY_DUR;
    let prevIdx = -1;
    const updateFn = (t) => {
      const idx = Math.min(n - 1, Math.floor((t % DUR) / DUR * n));
      if (idx < prevIdx) {
        agents.forEach(a => { a.out = false; a.x = (Math.random() - 0.5) * (W - 3); a.z = (Math.random() - 0.5) * (D - 3); });
      }
      prevIdx = idx;
      const evacuated = evacS ? evacS.vals[idx] : (aliveS ? total - aliveS.vals[idx] : 0);
      const sep = sepS ? sepS.vals[idx] : 1;
      const outTarget = Math.round(norm01(evacuated, 0, Math.max(...(evacS ? evacS.vals : [1]))) * AG);
      const doorX = 0, doorZ = D / 2 - 0.6;
      for (let i = 0; i < AG; i++) {
        const a = agents[i];
        const shouldOut = i < outTarget;
        if (!a.out) {
          let dx = doorX - a.x, dz = doorZ - a.z;
          const dl = Math.hypot(dx, dz) || 1;
          const sp = 0.045 * (1 + (1 - Math.min(sep, 1)) * 1.4);
          a.x += dx / dl * sp; a.z += dz / dl * sp;
          for (let j = 0; j < AG; j++) {
            if (j === i || agents[j].out) continue;
            const ox = a.x - agents[j].x, oz = a.z - agents[j].z;
            const od = Math.hypot(ox, oz);
            if (od > 0.001 && od < 0.7) { a.x += ox / od * 0.02; a.z += oz / od * 0.02; }
          }
          a.x = Math.max(-W / 2 + 0.6, Math.min(W / 2 - 0.6, a.x));
          a.z = Math.max(-D / 2 + 0.6, Math.min(D / 2 + 2.5, a.z));
          if (shouldOut && Math.abs(a.x - doorX) < 1.2 && a.z > D / 2 - 0.8) a.out = true;
          if (shouldOut && dl < 0.9) a.out = true;
        }
        const pressed = sep < 0.45;
        setAgent(crowd, i,
          a.out ? doorX + (i % 5 - 2) * 0.5 : a.x,
          a.out ? -1 : 0.55 + Math.abs(Math.sin(t * 6 + a.ph)) * 0.1,
          a.out ? D / 2 + 2 + (i % 3) : a.z,
          a.out ? 0 : Math.atan2(doorX - a.x, doorZ - a.z),
          a.out ? 0.001 : 1,
          a.out ? 0x00ffa3 : (pressed ? 0xff4d6d : (shouldOut ? 0xffb74d : 0x47e3d1)));
      }
      crowd.instanceMatrix.needsUpdate = true;
      if (crowd.instanceColor) crowd.instanceColor.needsUpdate = true;
      door.material.opacity = 0.25 + Math.sin(t * 3) * 0.1;
      const ang = t * 0.09;
      camera.position.set(Math.sin(ang) * 21, 14 + Math.sin(t * 0.15) * 2, Math.cos(ang) * 21);
      camera.lookAt(0, 1, 1);
      if (hud) hud.innerHTML =
        `<b style="color:#ffb74d">${meta.modelId}</b> · 紧急疏散<br>` +
        `<span style="color:#00ffa3">已撤离 ${Math.round(evacuated)}</span> / ${Math.round(total)} · ` +
        `<span style="color:${sep < 0.45 ? '#ff4d6d' : '#8fd8e8'}">最小间距 ${sep.toFixed(2)}${sep < 0.45 ? ' 拥挤!' : ''}</span><br>` +
        `tick ${idx + 1}/${n}` +
        (meta.note ? `<br><span style="color:#5a7a8b">${meta.note.slice(0, 38)}</span>` : '');
    };
    return { update: updateFn, type: 'world-evacuation' };
  }

  // ---- 集体恐慌：大理石广场 + 彩旗 + 喷泉环 ----
  function worldCrowdPanic(meta, seriesByName) {
    clearScene();
    const scene = getScene();
    addLights(scene);
    addGround(scene, 40, 0x0a1a2c);
    // 广场铺装（同心环浅色盘）
    const plaza = new THREE.Mesh(new THREE.CircleGeometry(15, 48),
      new THREE.MeshStandardMaterial({ color: 0x1e3a52, roughness: 0.7, metalness: 0.1 }));
    plaza.rotation.x = -Math.PI / 2;
    plaza.position.y = 0.01;
    plaza.receiveShadow = true;
    scene.add(plaza);
    [13.5, 10.5, 7.5].forEach((r, i) => {
      const ring = new THREE.Mesh(new THREE.RingGeometry(r, r + 0.18, 64),
        new THREE.MeshBasicMaterial({ color: [0x2a7a9a, 0x7a5aba, 0x2a7a9a][i], transparent: true, opacity: 0.3, side: THREE.DoubleSide }));
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = 0.02;
      scene.add(ring);
    });
    // 大理石纪念碑 + 金色饰环
    const monument = new THREE.Mesh(
      new THREE.CylinderGeometry(0.9, 1.3, 5, 12),
      new THREE.MeshStandardMaterial({ color: 0xd8e4ec, roughness: 0.35, metalness: 0.15 }));
    monument.position.y = 2.5;
    monument.castShadow = true;
    scene.add(monument);
    const halo = new THREE.Mesh(new THREE.TorusGeometry(1.4, 0.07, 10, 48),
      new THREE.MeshBasicMaterial({ color: 0xffd98c, transparent: true, opacity: 0.7 }));
    halo.rotation.x = Math.PI / 2;
    halo.position.y = 5.2;
    scene.add(halo);
    // 彩旗杆（六色小旗随风摆动）
    const flags = [];
    const flagCols = [0xff4d6d, 0xffb74d, 0x00ffa3, 0x00e5ff, 0xc084fc, 0xff8ac2];
    for (let i = 0; i < 6; i++) {
      const ang = i / 6 * Math.PI * 2;
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 3.4, 6),
        new THREE.MeshStandardMaterial({ color: 0x8a9ab0, metalness: 0.6, roughness: 0.4 }));
      pole.position.set(Math.cos(ang) * 14, 1.7, Math.sin(ang) * 14);
      scene.add(pole);
      const flag = new THREE.Mesh(new THREE.PlaneGeometry(1.1, 0.65),
        new THREE.MeshBasicMaterial({ color: flagCols[i], side: THREE.DoubleSide, transparent: true, opacity: 0.92 }));
      flag.position.set(Math.cos(ang) * 14 + 0.58, 3.0, Math.sin(ang) * 14);
      scene.add(flag);
      flags.push(flag);
    }
    addStreetLamps(scene, [[10, 10], [-10, -10], [10, -10], [-10, 10]]);
    addTrees(scene, [[16, 0], [-16, 0], [0, 16], [0, -16], [12, 12], [-12, -12]]);

    const pS = seriesByName('violence_frac') || seriesByName('participation') || seriesByName('I_frac') || seriesByName(seriesByName._first);
    const n = pS ? pS.vals.length : 2;
    const pLo = pS ? Math.min(...pS.vals) : 0, pHi = pS ? Math.max(...pS.vals) : 1;

    const AG = Math.round(110 + 130 * (window._vizDensity || 0.7));
    const crowd = makeCrowd(AG, 0x47e3d1);
    scene.add(crowd);
    const agents = [];
    for (let i = 0; i < AG; i++) {
      const r = 3 + Math.sqrt(Math.random()) * 11, th = Math.random() * Math.PI * 2;
      agents.push({ x: Math.cos(th) * r, z: Math.sin(th) * r, ph: Math.random() * 6, th: Math.random() });
    }
    const hud = makeHud();
    const DUR = PLAY_DUR;
    let prevP = 0;
    const updateFn = (t) => {
      const idx = Math.min(n - 1, Math.floor((t % DUR) / DUR * n));
      const p = pS ? norm01(pS.vals[idx], pLo, pHi) : 0.4;
      const k = Math.round(p * AG);
      for (let i = 0; i < AG; i++) {
        const a = agents[i];
        const active = i < k;
        const jump = active ? Math.abs(Math.sin(t * 5 + a.ph)) * 0.5 : 0;
        const sway = Math.sin(t * 1.4 + a.ph) * 0.04;
        setAgent(crowd, i, a.x, 0.55 + jump + sway, a.z, active ? a.ph + t * 0.5 : a.th,
                 active ? 1.15 : 1, active ? (i % 9 === 0 ? 0xffb74d : 0xff4d6d) : 0x47e3d1);
      }
      crowd.instanceMatrix.needsUpdate = true;
      if (crowd.instanceColor) crowd.instanceColor.needsUpdate = true;
      if (p - prevP > 0.12) {
        const wave = new THREE.Mesh(new THREE.RingGeometry(0.5, 0.8, 48),
          new THREE.MeshBasicMaterial({ color: 0xff4d6d, transparent: true, opacity: 0.5, side: THREE.DoubleSide }));
        wave.rotation.x = -Math.PI / 2;
        wave.position.y = 0.05;
        wave.userData.born = t;
        scene.add(wave);
      }
      prevP = p;
      scene.children.forEach(ch => {
        if (ch.userData && ch.userData.born !== undefined && ch.geometry && ch.geometry.type === 'RingGeometry') {
          const age = t - ch.userData.born;
          ch.scale.setScalar(1 + age * 9);
          ch.material.opacity = Math.max(0, 0.5 - age * 0.5);
          if (age > 1.1) { scene.remove(ch); ch.geometry.dispose(); ch.material.dispose(); }
        }
      });
      halo.rotation.z = t * 0.5;
      halo.material.color.setHSL(0.5 - p * 0.5, 0.9, 0.6);
      flags.forEach((f, i) => {
        f.rotation.y = Math.sin(t * 2.2 + i * 1.3) * 0.35;
        f.position.x += Math.sin(t * 2.2 + i * 1.3) * 0.003;
      });
      orbitCamera(t, 23, 13, 0.08);
      if (hud && pS) hud.innerHTML =
        `<b style="color:#ffb74d">${meta.modelId}</b> · 集体行为爆发<br>` +
        `<span style="color:#ff4d6d">参与/恐慌比例 ${(pS.vals[idx] * 100).toFixed(1)}%</span> · 爆发 ${k} 人<br>` +
        `tick ${idx + 1}/${n}` +
        (meta.note ? `<br><span style="color:#5a7a8b">${meta.note.slice(0, 38)}</span>` : '');
    };
    return { update: updateFn, type: 'world-crowd-panic' };
  }

  // ---- 居住分异：坡屋顶彩色小屋 + 社区花园 ----
  function worldSegregation(meta, seriesByName) {
    clearScene();
    const scene = getScene();
    addLights(scene);
    addGround(scene, 44, 0x0a1c2a);
    addRoad(scene, 0, 0, 2.0, 44, true);
    addRoad(scene, 0, 0, 2.0, 44, false);
    addStreetLamps(scene, [[3, 3], [-3, -3], [12, -12], [-12, 12]]);
    const sS = seriesByName('segregation') || seriesByName('segregation_index') ||
               seriesByName('similarity') || seriesByName('dissimilarity') || seriesByName(seriesByName._first);
    const n = sS ? sS.vals.length : 2;
    const sLo = sS ? Math.min(...sS.vals) : 0, sHi = sS ? Math.max(...sS.vals) : 1;

    const GX = 8, GZ = 8, CELL = 2.4;
    const houses = [];
    const houseGeo = new THREE.BoxGeometry(1.15, 0.85, 1.15);
    const roofGeo = new THREE.ConeGeometry(0.92, 0.6, 4);
    const palA = [0x1460a0, 0x1a7ab8, 0x2a8ac8];
    const palB = [0x8a30b0, 0xa04060, 0xb07030];
    for (let gx = 0; gx < GX; gx++) for (let gz = 0; gz < GZ; gz++) {
      const type = Math.random() > 0.5 ? 0 : 1;
      const bodyMat = new THREE.MeshStandardMaterial({
        color: (type ? palB : palA)[Math.floor(Math.random() * 3)],
        roughness: 0.55, metalness: 0.15,
        emissive: type ? 0x3a1050 : 0x0a3050, emissiveIntensity: 0.3,
      });
      const m = new THREE.Mesh(houseGeo, bodyMat);
      const px = (gx - GX / 2 + 0.5) * CELL, pz = (gz - GZ / 2 + 0.5) * CELL;
      m.position.set(px, 0.42, pz);
      m.castShadow = true;
      scene.add(m);
      // 坡屋顶（4棱锥，深一号色）
      const roof = new THREE.Mesh(roofGeo, new THREE.MeshStandardMaterial({
        color: type ? 0x4a1850 : 0x0a3a5a, roughness: 0.6, flatShading: true }));
      roof.position.set(px, 1.12, pz);
      roof.rotation.y = Math.PI / 4;
      roof.castShadow = true;
      scene.add(roof);
      // 花园地坪
      const garden = new THREE.Mesh(new THREE.PlaneGeometry(CELL * 0.86, CELL * 0.86),
        new THREE.MeshStandardMaterial({ color: type ? 0x24402a : 0x1a3a44, roughness: 0.9 }));
      garden.rotation.x = -Math.PI / 2;
      garden.position.set(px, 0.005, pz);
      garden.receiveShadow = true;
      scene.add(garden);
      houses.push({ m, roof, gx, gz, type, px, pz });
    }
    addTrees(scene, [[8, 10], [-8, -10], [10, -8], [-10, 8], [16, 2], [-16, -2]]);
    const hud = makeHud();
    const DUR = PLAY_DUR;
    const updateFn = (t) => {
      const idx = Math.min(n - 1, Math.floor((t % DUR) / DUR * n));
      const s = sS ? norm01(sS.vals[idx], sLo, sHi) : 0.5;
      houses.forEach((h, i) => {
        const jitter = (1 - s) * (Math.sin(i * 37.7) * 0.9);
        const cluster = s * (h.type === 0 ? -1 : 1) * 2.2;
        const targetX = (h.gx - GX / 2 + 0.5) * CELL + jitter + cluster;
        h.m.position.x += (targetX - h.m.position.x) * 0.06;
        h.roof.position.x = h.m.position.x;
        h.m.position.y = 0.42 + Math.sin(t * 1.5 + i) * 0.02;
        h.m.material.emissiveIntensity = 0.25 + s * 0.45 + Math.sin(t * 2 + i * 0.5) * 0.06;
      });
      orbitCamera(t, 24, 14, 0.07);
      if (hud && sS) hud.innerHTML =
        `<b style="color:#ffb74d">${meta.modelId}</b> · 居住分异<br>` +
        `分异指数 <span style="color:#c084fc">${sS.vals[idx].toFixed(3)}</span><br>` +
        `${s > 0.6 ? '明显聚类隔离' : s > 0.3 ? '分异形成中' : '混居状态'} · tick ${idx + 1}/${n}` +
        (meta.note ? `<br><span style="color:#5a7a8b">${meta.note.slice(0, 38)}</span>` : '');
    };
    return { update: updateFn, type: 'world-segregation' };
  }

  // ---- 城市交通：亮窗街区 + 红绿灯 + 路灯行道树 ----
  function worldTraffic(meta, seriesByName) {
    clearScene();
    const scene = getScene();
    addLights(scene);
    addGround(scene, 56, 0x0a1626);
    // 亮窗街区
    for (let bx = -1.5; bx <= 1.5; bx++) for (let bz = -1.5; bz <= 1.5; bz++) {
      if (Math.abs(bx) < 0.4 || Math.abs(bz) < 0.4) continue;
      const h = 1.2 + Math.random() * 5.5;
      const geo = new THREE.BoxGeometry(4.4, h, 4.4);
      const tex = makeWindowTexture(8, Math.max(6, Math.round(h * 3)), 0.4 + Math.random() * 0.3);
      const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
        color: [0x1a4a6a, 0x5a2a7a, 0x2a5a3a, 0x7a3a2a][Math.floor(Math.random() * 4)],
        roughness: 0.45, metalness: 0.5,
        emissive: 0xffffff, emissiveIntensity: 0.7, emissiveMap: tex }));
      m.position.set(bx * 11, h / 2, bz * 11);
      m.castShadow = true;
      scene.add(m);
    }
    // 车道 + 白色标线
    const laneMat = new THREE.MeshStandardMaterial({ color: 0x16222e, roughness: 0.8 });
    const dashMat = new THREE.MeshBasicMaterial({ color: 0x8fb4c4, transparent: true, opacity: 0.4 });
    for (let i = -1; i <= 1; i++) {
      const h1 = new THREE.Mesh(new THREE.PlaneGeometry(46, 2.4), laneMat);
      h1.rotation.x = -Math.PI / 2; h1.position.set(0, 0.01, i * 11); scene.add(h1);
      const h2 = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 46), laneMat);
      h2.rotation.x = -Math.PI / 2; h2.position.set(i * 11, 0.01, 0); scene.add(h2);
      for (let k = -20; k <= 20; k += 3) {
        const d1 = new THREE.Mesh(new THREE.PlaneGeometry(0.14, 1.0), dashMat);
        d1.rotation.x = -Math.PI / 2; d1.position.set(0, 0.02, i * 11 + k); scene.add(d1);
        const d2 = new THREE.Mesh(new THREE.PlaneGeometry(1.0, 0.14), dashMat);
        d2.rotation.x = -Math.PI / 2; d2.position.set(i * 11 + k, 0.02, 0); scene.add(d2);
      }
    }
    // 中心路口红绿灯（颜色随拥堵数据切换）
    const tlPole = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.09, 3.2, 6),
      new THREE.MeshStandardMaterial({ color: 0x1c3040, metalness: 0.5, roughness: 0.5 }));
    tlPole.position.set(1.6, 1.6, 1.6);
    scene.add(tlPole);
    const tlBox = new THREE.Mesh(new THREE.BoxGeometry(0.36, 1.0, 0.36),
      new THREE.MeshStandardMaterial({ color: 0x0a1420, roughness: 0.5 }));
    tlBox.position.set(1.6, 3.6, 1.6);
    scene.add(tlBox);
    const lampGeo = new THREE.SphereGeometry(0.13, 8, 8);
    const tlR = new THREE.Mesh(lampGeo, new THREE.MeshBasicMaterial({ color: 0x330a12, transparent: true, opacity: 0.9 }));
    const tlA = new THREE.Mesh(lampGeo, new THREE.MeshBasicMaterial({ color: 0x332208, transparent: true, opacity: 0.9 }));
    const tlG = new THREE.Mesh(lampGeo, new THREE.MeshBasicMaterial({ color: 0x0a3322, transparent: true, opacity: 0.9 }));
    tlR.position.set(1.6, 3.95, 1.6); tlA.position.set(1.6, 3.6, 1.6); tlG.position.set(1.6, 3.25, 1.6);
    scene.add(tlR, tlA, tlG);
    addStreetLamps(scene, [[5.5, 5.5], [-5.5, -5.5], [16.5, 5.5], [-16.5, -5.5], [5.5, -16.5], [-5.5, 16.5]]);
    addTrees(scene, [[8, 8], [-8, -8], [14, 14], [-14, -14], [8, -14], [-8, 14], [19, 0], [-19, 0], [0, 19], [0, -19]]);
    const fluxS = seriesByName('flux') || seriesByName('flow');
    const densS = seriesByName('density') || seriesByName('n_cars') || seriesByName(seriesByName._first);
    const n = Math.max(fluxS ? fluxS.vals.length : 0, densS ? densS.vals.length : 0, 2);
    const fluxLo = fluxS ? Math.min(...fluxS.vals) : 0, fluxHi = fluxS ? Math.max(...fluxS.vals) : 1;
    const densLo = densS ? Math.min(...densS.vals) : 0, densHi = densS ? Math.max(...densS.vals) : 1;

    const NC = 90;
    const carGeo = new THREE.BoxGeometry(0.5, 0.32, 1.0);
    const carMesh = new THREE.InstancedMesh(carGeo,
      new THREE.MeshStandardMaterial({ roughness: 0.4, metalness: 0.6 }), NC);
    scene.add(carMesh);
    const cars = [];
    for (let i = 0; i < NC; i++) {
      const horiz = Math.random() > 0.5, lane = [-11, 0, 11][i % 3] + (i % 2 ? 0.7 : -0.7);
      cars.push({ horiz, lane, t: Math.random() * 46, dir: i % 2 ? 1 : -1, sp: 0.06 + Math.random() * 0.05 });
    }
    const hud = makeHud();
    const DUR = PLAY_DUR;
    const updateFn = (t) => {
      const idx = Math.min(n - 1, Math.floor((t % DUR) / DUR * n));
      const flux = fluxS ? norm01(fluxS.vals[idx], fluxLo, fluxHi) : 0.5;
      const dens = densS ? norm01(densS.vals[idx], densLo, densHi) : 0.4;
      // 红绿灯随拥堵切换
      const congested = dens > 0.6;
      tlR.material.color.set(congested ? 0xff2233 : 0x330a12);
      tlG.material.color.set(congested ? 0x0a3322 : 0x22ff55);
      const speedScale = 0.25 + flux * 1.6;
      for (let i = 0; i < NC; i++) {
        const c = cars[i];
        c.t += c.sp * speedScale * (0.4 + dens);
        const w = ((c.t % 46) + 46) % 46 - 23;
        const x = c.horiz ? w * c.dir : c.lane;
        const z = c.horiz ? c.lane : w * c.dir;
        setAgent(carMesh, i, x, 0.28, z, c.horiz ? Math.PI / 2 * c.dir : 0, 1,
                 congested && i % 3 === 0 ? 0xff4d6d : [0x47e3d1, 0xffb74d, 0xc084fc, 0x68bbef][i % 4]);
      }
      carMesh.instanceMatrix.needsUpdate = true;
      if (carMesh.instanceColor) carMesh.instanceColor.needsUpdate = true;
      orbitCamera(t, 34, 34, 0.045);
      if (hud) hud.innerHTML =
        `<b style="color:#ffb74d">${meta.modelId}</b> · 城市交通流<br>` +
        (fluxS ? `通量 <span style="color:#00e5ff">${fluxS.vals[idx].toFixed(3)}</span> · ` : '') +
        (densS ? `密度 <span style="color:${dens > 0.7 ? '#ff4d6d' : '#8fd8e8'}">${densS.vals[idx].toFixed(2)}</span>` : '') +
        `<br>${congested ? '红灯 · 拥堵' : '绿灯 · 畅通'} · tick ${idx + 1}/${n}` +
        (meta.note ? `<br><span style="color:#5a7a8b">${meta.note.slice(0, 38)}</span>` : '');
    };
    return { update: updateFn, type: 'world-traffic' };
  }

  // ---- 宏观经济：亮窗工厂 + 烟雾粒子 + 坡屋顶住宅区 + 双色塔 ----
  function worldEconomy(meta, seriesByName) {
    clearScene();
    const scene = getScene();
    addLights(scene);
    addGround(scene, 50, 0x0a1a28);
    // 丘陵远景（高度顶点色）
    const hillGeo = new THREE.PlaneGeometry(70, 70, 20, 20);
    const hp = hillGeo.attributes.position.array;
    const hc = [];
    for (let i = 0; i < hp.length; i += 3) {
      const hV = Math.sin(hp[i] * 0.15) * 0.6 + Math.cos(hp[i + 1] * 0.12) * 0.6;
      hp[i + 2] = hV;
      const t01 = norm01(hV, -1.2, 1.2);
      const cc = new THREE.Color().setHSL(0.55 - t01 * 0.35, 0.5, 0.10 + t01 * 0.10);
      hc.push(cc.r, cc.g, cc.b);
    }
    hillGeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(hc), 3));
    hillGeo.computeVertexNormals();
    const hills = new THREE.Mesh(hillGeo, new THREE.MeshStandardMaterial({
      vertexColors: true, roughness: 1 }));
    hills.rotation.x = -Math.PI / 2;
    hills.position.y = -0.5;
    scene.add(hills);

    const wS = seriesByName('wage_share') || seriesByName('omega');
    const eS = seriesByName('employment') || seriesByName('lambda') || seriesByName(seriesByName._first);
    const n = Math.max(wS ? wS.vals.length : 0, eS ? eS.vals.length : 0, 2);
    const wLo = wS ? Math.min(...wS.vals) : 0, wHi = wS ? Math.max(...wS.vals) : 1;
    const eLo = eS ? Math.min(...eS.vals) : 0, eHi = eS ? Math.max(...eS.vals) : 1;

    // 亮窗工厂群 + 烟囱 + 烟雾粒子
    const factories = [];
    const smokeGeo = new THREE.SphereGeometry(0.22, 6, 6);
    const smokes = [];
    for (let f = 0; f < 3; f++) {
      const fx = -8 + f * 8, fz = -8;
      const body = new THREE.Mesh(new THREE.BoxGeometry(5, 2.6, 3.6),
        new THREE.MeshStandardMaterial({ color: 0x2a4a6a, roughness: 0.45, metalness: 0.45,
          emissive: 0xffffff, emissiveIntensity: 0.6,
          emissiveMap: makeWindowTexture(10, 5, 0.5) }));
      body.position.set(fx, 1.3, fz);
      body.castShadow = true;
      scene.add(body);
      const chim = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.4, 3.4, 8),
        new THREE.MeshStandardMaterial({ color: 0x4a3a30, roughness: 0.7 }));
      chim.position.set(fx + 1.6, 4, fz - 1);
      scene.add(chim);
      factories.push({ fx, fz, chim });
      for (let s = 0; s < 5; s++) {
        const sm = new THREE.Mesh(smokeGeo,
          new THREE.MeshBasicMaterial({ color: 0x8a9ab0, transparent: true, opacity: 0.25 }));
        scene.add(sm);
        smokes.push({ m: sm, fx: fx + 1.6, fz: fz - 1, ph: s / 5 });
      }
    }
    // 坡屋顶住宅区
    for (let hx = 0; hx < 5; hx++) {
      const hh = 0.9 + Math.random() * 0.8;
      const home = new THREE.Mesh(new THREE.BoxGeometry(2, hh, 2),
        new THREE.MeshStandardMaterial({ color: [0x2a6a8a, 0x7a4a8a, 0x8a6a3a, 0x3a8a5a, 0x8a3a4a][hx],
          roughness: 0.55, emissive: 0x47e3d1, emissiveIntensity: 0.12 }));
      home.position.set(-10 + hx * 5, hh / 2, 9);
      home.castShadow = true;
      scene.add(home);
      const roof = new THREE.Mesh(new THREE.ConeGeometry(1.55, 0.7, 4),
        new THREE.MeshStandardMaterial({ color: 0x8a4a30, roughness: 0.6, flatShading: true }));
      roof.position.set(-10 + hx * 5, hh + 0.35, 9);
      roof.rotation.y = Math.PI / 4;
      scene.add(roof);
    }
    // 家↔厂道路
    addRoad(scene, 0, 0.5, 1.8, 20, false);

    const AG = 60;
    const crowd = makeCrowd(AG, 0x47e3d1);
    scene.add(crowd);
    const workers = [];
    for (let i = 0; i < AG; i++) workers.push({ ph: i / AG, side: i % 2 ? 1 : -1 });
    const wageTower = new THREE.Mesh(new THREE.CylinderGeometry(1.1, 1.3, 1, 24),
      new THREE.MeshStandardMaterial({ color: 0x0d3a4a, emissive: 0x00e5ff, emissiveIntensity: 0.6, transparent: true, opacity: 0.85 }));
    wageTower.position.set(14, 0.5, -2);
    scene.add(wageTower);
    const profitTower = new THREE.Mesh(new THREE.CylinderGeometry(1.1, 1.3, 1, 24),
      new THREE.MeshStandardMaterial({ color: 0x4a2a1a, emissive: 0xffb74d, emissiveIntensity: 0.6, transparent: true, opacity: 0.85 }));
    profitTower.position.set(14, 0.5, 2.5);
    scene.add(profitTower);
    const hud = makeHud();
    const DUR = PLAY_DUR;
    const updateFn = (t) => {
      const idx = Math.min(n - 1, Math.floor((t % DUR) / DUR * n));
      const wage = wS ? norm01(wS.vals[idx], wLo, wHi) : 0.5;
      const emp = eS ? norm01(eS.vals[idx], eLo, eHi) : 0.5;
      wageTower.scale.y = 1 + wage * 8;
      wageTower.position.y = (1 + wage * 8) / 2;
      profitTower.scale.y = 1 + (1 - wage) * 8;
      profitTower.position.y = (1 + (1 - wage) * 8) / 2;
      const working = Math.round(emp * AG);
      for (let i = 0; i < AG; i++) {
        const wk = workers[i];
        const cycle = (t * 0.12 + wk.ph) % 1;
        const atWork = i < working;
        const z = atWork ? 9 - cycle * 17 * wk.side : 9 - (1 - cycle) * 17 * wk.side;
        const x = -10 + (i % 10) * 2.1 + Math.sin(t + i) * 0.15;
        setAgent(crowd, i, atWork ? x : x + 2, 0.55 + Math.abs(Math.sin(t * 5 + i)) * 0.08,
                 Math.max(-8, Math.min(9, Math.abs(z) < 0 ? 0 : z)),
                 z > 0 ? Math.PI : 0, 1, atWork ? 0xffb74d : 0x47e3d1);
      }
      crowd.instanceMatrix.needsUpdate = true;
      if (crowd.instanceColor) crowd.instanceColor.needsUpdate = true;
      // 烟雾粒子上升循环
      smokes.forEach(sm => {
        const ph = ((t * 0.25 + sm.ph) % 1);
        sm.m.position.set(sm.fx + Math.sin(t + sm.ph * 9) * 0.3, 5.6 + ph * 3.2, sm.fz);
        const o = Math.max(0, 0.3 - ph * 0.3);
        sm.m.material.opacity = o * (0.4 + emp * 0.6);
        sm.m.scale.setScalar(0.7 + ph * 1.6);
      });
      orbitCamera(t, 28, 15, 0.06);
      if (hud) hud.innerHTML =
        `<b style="color:#ffb74d">${meta.modelId}</b> · 宏观经济循环<br>` +
        (wS ? `工资份额 <span style="color:#00e5ff">${(wS.vals[idx] * 100).toFixed(1)}%</span> · ` : '') +
        (eS ? `就业 <span style="color:#ffb74d">${(eS.vals[idx] * 100).toFixed(1)}%</span>` : '') +
        `<br>通勤 ${working}/${AG} · tick ${idx + 1}/${n}` +
        (meta.note ? `<br><span style="color:#5a7a8b">${meta.note.slice(0, 38)}</span>` : '');
    };
    return { update: updateFn, type: 'world-economy' };
  }

  // ---- 金融市场：环形行情大屏（动态贴图）+ 彩色交易台 ----
  function worldMarket(meta, seriesByName) {
    clearScene();
    const scene = getScene();
    addLights(scene);
    addGround(scene, 44, 0x081420);
    // 环形交易台（多彩）
    const deskCols = [0x1a5a7a, 0x5a2a8a, 0x8a5a1a, 0x2a6a4a];
    for (let i = 0; i < 14; i++) {
      const ang = i / 14 * Math.PI * 2;
      const desk = new THREE.Mesh(new THREE.BoxGeometry(2.4, 0.9, 0.9),
        new THREE.MeshStandardMaterial({ color: deskCols[i % 4], roughness: 0.5,
          emissive: deskCols[i % 4], emissiveIntensity: 0.18 }));
      desk.position.set(Math.cos(ang) * 13, 0.45, Math.sin(ang) * 13);
      desk.rotation.y = -ang + Math.PI / 2;
      scene.add(desk);
    }
    // 中央行情大屏（canvas 动态贴图，滚动行情条）
    const tc = document.createElement('canvas');
    tc.width = 512; tc.height = 64;
    const tg = tc.getContext('2d');
    const tickTex = new THREE.CanvasTexture(tc);
    tickTex.colorSpace = THREE.SRGBColorSpace;
    tickTex.wrapS = THREE.RepeatWrapping;
    const board = new THREE.Mesh(new THREE.CylinderGeometry(4.8, 4.8, 2.6, 32, 1, true),
      new THREE.MeshBasicMaterial({ map: tickTex, transparent: true, opacity: 0.92,
        side: THREE.DoubleSide, emissive: 0xffffff, emissiveMap: tickTex, emissiveIntensity: 0.55 }));
    board.position.y = 2.6;
    scene.add(board);
    const drawTicker = (vals) => {
      tg.fillStyle = '#04101c'; tg.fillRect(0, 0, 512, 64);
      const names = ['DAYAN', 'INDEX A', 'INDEX B', 'FUTURES'];
      vals.forEach((v, i) => {
        const up = v >= 0;
        tg.fillStyle = up ? '#00ffa3' : '#ff4d6d';
        tg.font = 'bold 15px monospace';
        tg.fillText(`${names[i % 4]} ${up ? '▲' : '▼'} ${Math.abs(v).toFixed(2)}`, 8 + i * 128, 26);
        tg.fillRect(8 + i * 128, 38, Math.min(110, Math.abs(v) * 6), 6);
      });
      tickTex.needsUpdate = true;
    };
    const priceS = seriesByName('price') || seriesByName('p') || seriesByName('wealth_mean') || seriesByName(seriesByName._first);
    const volS = seriesByName('volume') || seriesByName('n_trades');
    const n = priceS ? priceS.vals.length : 2;
    const AG = 28;
    const crowd = makeCrowd(AG, 0x47e3d1);
    scene.add(crowd);
    const hud = makeHud();
    const DUR = PLAY_DUR;
    let lastTick = -1;
    const updateFn = (t) => {
      const idx = Math.min(n - 1, Math.floor((t % DUR) / DUR * n));
      const upTrend = idx > 0 && priceS ? priceS.vals[idx] >= priceS.vals[Math.max(0, idx - 1)] : true;
      const volFrac = volS ? norm01(volS.vals[Math.min(n - 1, idx)], Math.min(...volS.vals), Math.max(...volS.vals)) : 0.4;
      // 行情大屏每 tick 重绘
      if (priceS && idx !== lastTick) {
        lastTick = idx;
        const vals = [];
        for (let k = 0; k < 4; k++) {
          const src = Math.max(0, Math.min(n - 1, idx - k));
          const base = priceS.vals[src];
          vals.push((upTrend ? 1 : -1) * base * (10 + k * 3));
        }
        drawTicker(vals);
      }
      board.rotation.y = t * 0.12;
      for (let i = 0; i < AG; i++) {
        const ang = i / AG * Math.PI * 2;
        const excited = volFrac > 0.6;
        setAgent(crowd, i, Math.cos(ang) * 11.5, 0.55 + (excited ? Math.abs(Math.sin(t * 6 + i)) * 0.3 : 0), Math.sin(ang) * 11.5,
                 -ang + Math.PI / 2, 1, excited && i % 3 === 0 ? 0xffb74d : 0x47e3d1);
      }
      crowd.instanceMatrix.needsUpdate = true;
      if (crowd.instanceColor) crowd.instanceColor.needsUpdate = true;
      orbitCamera(t, 24, 13, 0.07);
      if (hud && priceS) hud.innerHTML =
        `<b style="color:#ffb74d">${meta.modelId}</b> · 市场交易大厅<br>` +
        `价格 <span style="color:#${upTrend ? '00ffa3' : 'ff4d6d'}">${priceS.vals[idx].toFixed(3)}</span>` +
        (volS ? ` · 成交量 ${volS.vals[Math.min(n - 1, idx)].toFixed(1)}` : '') +
        `<br>${upTrend ? '上涨' : '下跌'} · tick ${idx + 1}/${n}` +
        (meta.note ? `<br><span style="color:#5a7a8b">${meta.note.slice(0, 38)}</span>` : '');
    };
    return { update: updateFn, type: 'world-market' };
  }

  // ---- 网络级联：彩虹节点 + 脉冲核心 ----
  function worldNetwork(meta, seriesByName) {
    clearScene();
    const scene = getScene();
    addLights(scene);
    const actS = seriesByName('cascade_size') || seriesByName('failed') ||
                 seriesByName('adoption') || seriesByName('informed_frac') || seriesByName(seriesByName._first);
    const n = actS ? actS.vals.length : 2;
    const aLo = actS ? Math.min(...actS.vals) : 0, aHi = actS ? Math.max(...actS.vals) : 1;

    const NN = 110;
    const nodes = [];
    const nodeGeo = new THREE.SphereGeometry(0.22, 10, 10);
    const nodeGroup = new THREE.Group();
    for (let i = 0; i < NN; i++) {
      const phi = Math.acos(1 - 2 * (i + 0.5) / NN);
      const theta = Math.PI * (1 + Math.sqrt(5)) * i;
      const r = 6.5 + Math.random() * 1.5;
      const x = r * Math.sin(phi) * Math.cos(theta), y = r * Math.cos(phi), z = r * Math.sin(phi) * Math.sin(theta);
      const hub = i % 9 === 0;
      // 彩虹节点（HSL 色相铺满）
      const mat = new THREE.MeshBasicMaterial({
        color: new THREE.Color().setHSL((i / NN) * 0.85 + 0.05, 0.75, hub ? 0.65 : 0.55) });
      const m = new THREE.Mesh(nodeGeo, mat);
      m.position.set(x, y, z);
      m.scale.setScalar(hub ? 2 : 1);
      nodeGroup.add(m);
      nodes.push({ m, x, y, z, hub });
    }
    scene.add(nodeGroup);
    // 脉冲核心（中心发光球 + 光环）
    const core = new THREE.Mesh(new THREE.SphereGeometry(0.9, 20, 20),
      new THREE.MeshBasicMaterial({ color: 0xc084fc, transparent: true, opacity: 0.75 }));
    scene.add(core);
    const coreRing = new THREE.Mesh(new THREE.TorusGeometry(1.5, 0.05, 8, 48),
      new THREE.MeshBasicMaterial({ color: 0x9fe8ff, transparent: true, opacity: 0.5 }));
    scene.add(coreRing);
    const lineMat = new THREE.LineBasicMaterial({ color: 0x2a5a8a, transparent: true, opacity: 0.3 });
    for (let i = 0; i < NN; i += 2) {
      const j = (i * 7 + 13) % NN;
      const geo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(nodes[i].x, nodes[i].y, nodes[i].z),
        new THREE.Vector3(nodes[j].x, nodes[j].y, nodes[j].z)]);
      scene.add(new THREE.Line(geo, lineMat));
    }
    const hud = makeHud();
    const DUR = PLAY_DUR;
    const updateFn = (t) => {
      const idx = Math.min(n - 1, Math.floor((t % DUR) / DUR * n));
      const frac = actS ? norm01(actS.vals[idx], aLo, aHi) : 0.4;
      const k = Math.round(frac * NN);
      for (let i = 0; i < NN; i++) {
        const nd = nodes[i];
        const active = i < k;
        nd.m.position.y = nd.y + Math.sin(t * 0.9 + i) * 0.18;
        const base = new THREE.Color().setHSL((i / NN) * 0.85 + 0.05, 0.75, nd.hub ? 0.65 : 0.55);
        nd.m.material.color.copy(active ? base.clone().lerp(new THREE.Color(nd.hub ? 0xffb74d : 0xff4d6d), 0.75) : base);
      }
      core.scale.setScalar(1 + Math.sin(t * 2.4) * 0.15 + frac * 0.5);
      core.material.color.setHSL(0.75 - frac * 0.45, 0.8, 0.6);
      coreRing.rotation.x = t * 0.6; coreRing.rotation.y = t * 0.4;
      const ang = t * 0.07;
      camera.position.set(Math.sin(ang) * 19, 7 + Math.sin(t * 0.14) * 3, Math.cos(ang) * 19);
      camera.lookAt(0, 0, 0);
      if (hud && actS) hud.innerHTML =
        `<b style="color:#ffb74d">${meta.modelId}</b> · 网络级联<br>` +
        `<span style="color:#ff4d6d">级联/激活 ${(actS.vals[idx] * 100).toFixed(1)}%</span> · ${k}/${NN} 节点<br>` +
        `tick ${idx + 1}/${n}` +
        (meta.note ? `<br><span style="color:#5a7a8b">${meta.note.slice(0, 38)}</span>` : '');
    };
    return { update: updateFn, type: 'world-network' };
  }

  // ---- 通用地貌：高度顶点色山丘（翠绿→琥珀→雪顶）+ 岩石点缀 ----
  function worldSurface(meta, seriesByName, names, seriesList) {
    clearScene();
    const scene = getScene();
    addLights(scene);
    addGround(scene, 60, 0x0a1a1e);

    const n = seriesList.length ? seriesList[0].length : 2;
    const SEG = 36, SIZE = 40;
    const geo = new THREE.PlaneGeometry(SIZE, SIZE, SEG, SEG);
    // 高度→彩色（顶点色，动态更新）
    geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(geo.attributes.position.count * 3), 3));
    const mat = new THREE.MeshStandardMaterial({
      vertexColors: true, transparent: true, opacity: 0.95,
      roughness: 0.65, metalness: 0.15,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.rotation.x = -Math.PI / 2;
    scene.add(mesh);
    const wire = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({
      color: 0x2a8aaa, wireframe: true, transparent: true, opacity: 0.14 }));
    wire.rotation.x = -Math.PI / 2;
    wire.position.y = 0.02;
    scene.add(wire);

    const peak = new THREE.Mesh(new THREE.SphereGeometry(0.45, 12, 12),
      new THREE.MeshBasicMaterial({ color: 0xffb74d }));
    scene.add(peak);
    const peakGlow = new THREE.PointLight(0xffb74d, 1.2, 14);
    scene.add(peakGlow);

    // 岩石点缀（Dodecahedron，紫灰）
    for (let i = 0; i < 10; i++) {
      const rock = new THREE.Mesh(new THREE.DodecahedronGeometry(0.3 + Math.random() * 0.5),
        new THREE.MeshStandardMaterial({ color: 0x5a4a7a, roughness: 0.7, flatShading: true }));
      const rx = (Math.random() - 0.5) * SIZE * 0.8, rz = (Math.random() - 0.5) * SIZE * 0.8;
      rock.position.set(rx, 0.25, rz);
      rock.rotation.set(Math.random() * 3, Math.random() * 3, Math.random() * 3);
      scene.add(rock);
    }
    // 水晶簇（彩色呼吸）
    const crystals = [];
    const crysCols = [0x00e5ff, 0xc084fc, 0xffb74d];
    for (let s = 0; s < 3; s++) {
      const c = new THREE.Mesh(new THREE.OctahedronGeometry(0.7 + s * 0.25),
        new THREE.MeshStandardMaterial({ color: 0x1a5a75, emissive: crysCols[s],
          emissiveIntensity: 0.5, transparent: true, opacity: 0.85, roughness: 0.2, metalness: 0.6 }));
      c.position.set(-6 + s * 6, 2, -13);
      scene.add(c);
      crystals.push(c);
    }

    const hud = makeHud();
    const DUR = PLAY_DUR;
    const colAttr = geo.getAttribute('color');
    const tmpCol = new THREE.Color();
    const updateFn = (t) => {
      const idx = Math.min(n - 1, Math.floor((t % DUR) / DUR * n));
      const pos = geo.attributes.position.array;
      let maxH = 0, px = 0, py = 0;
      const wind = t * 0.35;
      for (let i = 0, vi = 0; i < pos.length; i += 3, vi++) {
        const gx = pos[i], gy = pos[i + 1];
        // 自然地貌：山丘 + 雪线（高度顶点色：翠绿→琥珀→雪白）
        const h = 1.1
          + Math.sin(gx * 0.22 + 1.7) * Math.cos(gy * 0.19 + 0.6) * 1.2
          + Math.sin(gx * 0.53) * Math.cos(gy * 0.47) * 0.5
          + Math.sin(gx * 0.5 + wind) * 0.08 + Math.cos(gy * 0.5 + wind * 0.7) * 0.08;
        pos[i + 2] = h;
        const t01 = norm01(h, 0.4, 2.9);
        tmpCol.setHSL(0.38 - t01 * 0.32, 0.65, 0.18 + t01 * 0.5);
        colAttr.setXYZ(vi, tmpCol.r, tmpCol.g, tmpCol.b);
        if (h > maxH) { maxH = h; px = gx; py = gy; }
      }
      geo.attributes.position.needsUpdate = true;
      colAttr.needsUpdate = true;
      geo.computeVertexNormals();
      peak.position.set(px, maxH + 0.6, py);
      peakGlow.position.set(px, maxH + 1, py);
      crystals.forEach((c, s) => {
        c.rotation.y = t * (0.5 + s * 0.2);
        c.position.y = 1.5 + Math.sin(t * 1.5 + s * 2) * 0.3;
        c.material.emissiveIntensity = 0.4 + Math.sin(t * 1.2 + s * 2.1) * 0.2;
      });
      orbitCamera(t, 27, 14, 0.06);
      if (hud) {
        const rows = names.slice(0, 3).map((nm, s) =>
          `<span style="color:#00e5ff">${nm}</span>=${seriesList[s][idx].toPrecision(4)}`).join(' · ');
        hud.innerHTML =
          `<b style="color:#ffb74d">${meta.modelId}</b> · 观测地貌<br>${rows}<br>tick ${idx + 1}/${n}` +
          (meta.note ? `<br><span style="color:#5a7a8b">${meta.note.slice(0, 38)}</span>` : '');
      }
    };
    return { update: updateFn, type: 'world-surface' };
  }

  // ---- visualize 调度：按模型族构建对应的真实世界 ----
  function visualize(modelId, observations, meta = {}) {
    meta.modelId = modelId || 'MODEL';
    const { names, series } = extractSeries(observations);
    const nameSet = {};
    names.forEach((nm, i) => { nameSet[nm.toLowerCase()] = { vals: series[i] }; });
    const byName = (k) => {
      const e = k ? nameSet[String(k).toLowerCase()] : null;
      return e || null;   // 返回 {vals:[...]} 或 null
    };
    byName._first = names.length ? names[0].toLowerCase() : null;

    // 族类 → 世界场景（456 模型全覆盖：先具体族后宽泛族，前缀命中即停）
    const mid = (modelId || '').toUpperCase();
    const rules = [
      [/^NET05[2-9]|^NET06[0-9]|^NET07[0-2]/, worldEpidemic],
      [/^APP/, worldEpidemic],                       // 应用场景 → 城市生活
      [/^NET11[3-9]|^NET120/, worldEvacuation],
      [/^BEH00[5-6]|^BEH014/, worldCrowdPanic],
      [/^BEH00[1-4]/, worldSegregation],
      [/^NET09[5-9]|^NET10[0-9]|^NET11[0-2]/, worldTraffic],
      [/^ECO04[6-9]|^ECO05[0-6]/, worldMarket],
      [/^ECO\d{3}/, worldEconomy],                   // 经济全族（市场段已被上条拦截）
      [/^(BEH|SYS|NET)/, worldNetwork],              // 其余行为/博弈/RL/LLM主体/系统动力学/NET 剩余 → 彩虹节点网络
    ];
    for (const [re, builder] of rules) {
      if (re.test(mid)) {
        currentScene = builder(meta, byName);
        window._vizData = { names, series, n: names.length ? series[0].length : 0 };
        attachWeather(getScene());
        return currentScene.type;
      }
    }
    if (!names.length) {
      // MET 方法演示返回单条诊断观测 → 彩色数据地貌（无数据也渲染自然山丘）
      if (/^MET/.test(mid)) { currentScene = worldSurface(meta, byName, [], []); attachWeather(getScene()); return currentScene.type; }
      autoDetect(modelId);
      attachWeather(getScene());
      return currentScene ? currentScene.type : null;
    }
    currentScene = worldSurface(meta, byName, names, series);
    window._vizData = { names, series, n: names.length ? series[0].length : 0 };
    attachWeather(getScene());
    return currentScene.type;
  }

  // ============================================================
  // 族类氛围场景（无数据时）
  // ============================================================

  function buildCityScene(params) {
    clearScene();
    const scene = getScene();
    addLights(scene);
    addGround(scene, 190, 0x5a6470);
    // ===== 大都市路网：7 条主干道 × 两轴 = 6x6 = 36 街区 =====
    const R = [-45, -30, -15, 0, 15, 30, 45];
    R.forEach(x => { addRoad(scene, x, 0, 3.0, 190, false); addSidewalks(scene, x, 0, 3.0, 190, false); });
    R.forEach(z => { addRoad(scene, 0, z, 3.0, 190, true); addSidewalks(scene, 0, z, 3.0, 190, true); });
    // 路口斑马线（采样主要路口）
    [[0, 0], [-15, 0], [15, 0], [0, -15], [0, 15], [-30, -30], [30, 30], [-30, 30], [30, -30]]
      .forEach(([x, z]) => addCrosswalk(scene, x, z, 3.0));
    // ===== 街区：中心 CBD 高层 → 中环 → 外围 =====
    const B = [-37.5, -22.5, -7.5, 7.5, 22.5, 37.5];
    const roofCols = [0x8a8a92, 0x6a6a74, 0x9a7a6a, 0x7a8a92, 0x9a8a7a];
    const parks = new Set(['-22.5,22.5', '22.5,-22.5', '-37.5,-37.5', '37.5,37.5']);
    let treeCount = 0;
    const parkTreeSpots = [];
    B.forEach(bx => B.forEach(bz => {
      const isPark = parks.has(bx + ',' + bz);
      if (isPark) {
        const plate = new THREE.Mesh(new THREE.PlaneGeometry(13.5, 13.5),
          new THREE.MeshStandardMaterial({ color: 0x5a9a4a, roughness: 0.9 }));
        plate.rotation.x = -Math.PI / 2; plate.position.set(bx, 0.006, bz);
        plate.receiveShadow = true;
        scene.add(plate);
        const pond = new THREE.Mesh(new THREE.CircleGeometry(2.6, 24),
          new THREE.MeshStandardMaterial({ color: 0x3a8ac0, roughness: 0.25, metalness: 0.1 }));
        pond.rotation.x = -Math.PI / 2; pond.position.set(bx + 1.6, 0.012, bz - 1.6);
        scene.add(pond);
        const path = new THREE.Mesh(new THREE.PlaneGeometry(12.4, 0.9),
          new THREE.MeshStandardMaterial({ color: 0xc0b090, roughness: 0.9 }));
        path.rotation.x = -Math.PI / 2; path.position.set(bx, 0.011, bz + 3.4);
        scene.add(path);
        for (let t2 = 0; t2 < 12; t2++) {
          parkTreeSpots.push([bx + (Math.random() - 0.5) * 11, bz + (Math.random() - 0.5) * 11]);
          treeCount++;
        }
        return;
      }
      const dist = Math.max(Math.abs(bx), Math.abs(bz));
      const tier = dist <= 7.5 ? 0 : dist <= 22.5 ? 1 : 2;
      const hLo = [9, 4, 2][tier], hHi = [17, 10, 6][tier];
      // 2x2 栋/街区（36 街区 ≈ 130 栋）
      for (const ox of [-2.5, 2.5]) for (const oz of [-2.5, 2.5]) {
  
        const h = hLo + Math.random() * (hHi - hLo);
        const w = 3.4 + Math.random() * 0.7, d = 3.4 + Math.random() * 0.7;
        const x = bx + ox + (Math.random() - 0.5) * 0.5;
        const z = bz + oz + (Math.random() - 0.5) * 0.5;
        const kk = Math.random() < 0.25 ? 'glass' : Math.random() < 0.8 ? 'windows' : 'concrete';
        const wallHex = ['#d8cfc0', '#c9beb0', '#b8c0c8', '#c9b8ac', '#d9d4c8'][Math.floor(Math.random() * 5)];
        const tex = makeWindowTexture(Math.max(5, Math.round(w * 4)), Math.max(10, Math.round(h * 4)),
          kk === 'glass' ? 0.15 : 0.3 + Math.random() * 0.35, wallHex);
        let mat;
        if (kk === 'glass') {
          mat = new THREE.MeshPhysicalMaterial({ color: 0xbcccd8, metalness: 0.4, roughness: 0.32,
            envMapIntensity: 1.15, map: tex,
            emissive: 0xffe8b0, emissiveIntensity: 0.2, emissiveMap: tex });
        } else if (kk === 'concrete') {
          mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.82, metalness: 0.04,
            map: tex, flatShading: true,
            emissive: 0xffe8b0, emissiveIntensity: 0.14, emissiveMap: tex });
        } else {
          mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.62, metalness: 0.06,
            map: tex, flatShading: true,
            emissive: 0xffe8b0, emissiveIntensity: 0.16, emissiveMap: tex });
        }
        let mesh;
        if (kk === 'glass' && h > 11 && Math.random() < 0.45) {
          mesh = new THREE.Mesh(new THREE.CylinderGeometry(w * 0.48, w * 0.52, h, 18), mat);
        } else {
          mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
        }
        mesh.position.set(x, h / 2, z);
        mesh.castShadow = true; mesh.receiveShadow = true;
        scene.add(mesh);
        const skirt = new THREE.Mesh(new THREE.BoxGeometry(w * 1.04, 0.5, d * 1.04),
          new THREE.MeshStandardMaterial({ color: new THREE.Color(wallHex).multiplyScalar(0.55) }));
        skirt.position.set(x, 0.25, z);
        scene.add(skirt);
        if (kk === 'glass' && h > 11) {
          const dome = new THREE.Mesh(new THREE.SphereGeometry(w * 0.48, 16, 10),
            new THREE.MeshPhysicalMaterial({ color: 0x5aaad0, metalness: 0.4, roughness: 0.3, envMapIntensity: 1.1 }));
          dome.position.set(x, h, z);
          scene.add(dome);
        } else {
          const capCol = roofCols[Math.floor(Math.random() * 4)];
          const cap = new THREE.Mesh(new THREE.BoxGeometry(w * 1.02, 0.08, d * 1.02),
            new THREE.MeshStandardMaterial({ color: capCol, roughness: 0.88 }));
          cap.position.set(x, h + 0.04, z);
          scene.add(cap);
          addParapet(scene, x, h + 0.04, z, w * 1.02, d * 1.02, capCol);
        }
        if (Math.random() < 0.55) {
          for (let a = 0; a < 1 + Math.floor(Math.random() * 2); a++) {
            const ac = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.22, 0.32),
              new THREE.MeshStandardMaterial({ color: 0x5a6a7a, roughness: 0.5, metalness: 0.4 }));
            ac.position.set(x + (Math.random() - 0.5) * w * 0.5, h + 0.2, z + (Math.random() - 0.5) * d * 0.5);
            ac.rotation.y = Math.random() * 3;
            scene.add(ac);
          }
        }
        if (Math.random() < 0.25 && h > 5) {
          const wt = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.3, 0.55, 8),
            new THREE.MeshStandardMaterial({ color: 0x8a5a3a, roughness: 0.6 }));
          wt.position.set(x + (Math.random() - 0.5) * w * 0.4, h + 0.35, z + (Math.random() - 0.5) * d * 0.4);
          scene.add(wt);
          const wtc = new THREE.Mesh(new THREE.ConeGeometry(0.33, 0.25, 8),
            new THREE.MeshStandardMaterial({ color: 0x6a4a30, roughness: 0.6 }));
          wtc.position.set(wt.position.x, h + 0.72, wt.position.z);
          scene.add(wtc);
        }
        if (h > 13) {
          const ant = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.05, 1.3, 5),
            new THREE.MeshStandardMaterial({ color: 0x2a3c50, metalness: 0.6, roughness: 0.5 }));
          ant.position.set(x, h + 0.65, z);
          scene.add(ant);
          const tip = new THREE.Mesh(new THREE.SphereGeometry(0.1, 6, 6),
            new THREE.MeshBasicMaterial({ color: 0xff3355, transparent: true, opacity: 0.9 }));
          tip.position.set(x, h + 1.35, z);
          scene.add(tip);
          blinkers.push(tip);
          addGlowSprite(scene, x, h + 1.35, z, 1.2, '#ff3355', 0.35);
        }
      }
    }));
    // 远景天际线（雾中剪影层）
    addSkyline(scene, 118, 64);
    // 路口路灯（点光源限流 1/3，其余纯辉光）
    const lamps = [];
    [[-15, -15], [15, 15], [-30, 0], [30, 0], [0, -30], [0, 30], [-45, 15], [45, -15]]
      .forEach(([a, b]) => lamps.push([a + 2.3, b + 2.3]));
    addStreetLamps(scene, lamps, 2);
    // 行道树（沿全部主干道）
    const ts = [];
    R.forEach(rc => {
      for (let k = 0; k < 14; k++) {
        const along = -88 + k * 13 + Math.random() * 5;
        const off = 2.5 + Math.random() * 0.4;
        ts.push([rc + off, along]);
        ts.push([along, rc - off]);
      }
    });
    ts.push(...parkTreeSpots);
    addTrees(scene, ts);
    camera.position.set(26, 56, 26);
    camera.lookAt(0, 0, 0);

    // 车流（7 路全网 100 辆）
    const cars = new THREE.Group();
    const carGeo = new THREE.BoxGeometry(0.36, 0.2, 0.78);
    const carData = [];
    for (let i = 0; i < (params.cars || 100); i++) {
      const mat = new THREE.MeshStandardMaterial({ color: [0xe8e8ee, 0x2a2a34, 0xd94a4a, 0x4a7ad9, 0xe0b45c][i % 5], roughness: 0.4, metalness: 0.3 });
      const mesh = new THREE.Mesh(carGeo, mat);
      const cabin = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.16, 0.42),
        new THREE.MeshStandardMaterial({ color: 0x1a2634, roughness: 0.2, metalness: 0.4 }));
      cabin.position.set(0, 0.16, -0.04);
      mesh.add(cabin);
      const rc = R[i % R.length];
      const horiz = (i % 2) === 0;
      const laneOff = (i % 4 < 2) ? 0.8 : -0.8;
      const dir = (i % 4 < 2) ? 1 : -1;
      cars.add(mesh);
      carData.push({ mesh, rc, horiz, laneOff, dir, speed: 0.045 + Math.random() * 0.05, t: Math.random() * 190 });
    }
    scene.add(cars);

    const updateFn = (t, dt) => {
      orbitCamera(t, 52, 44, 0.028, 0);
      carData.forEach(cd => {
        cd.t += cd.speed * cd.dir;
        const wrapped = ((cd.t % 190) + 190) % 190 - 95;
        if (cd.horiz) cd.mesh.position.set(wrapped, 0.27, cd.rc + cd.laneOff);
        else cd.mesh.position.set(cd.rc + cd.laneOff, 0.27, wrapped);
        cd.mesh.rotation.y = cd.horiz ? (cd.dir > 0 ? 0 : Math.PI) : (cd.dir > 0 ? Math.PI / 2 : -Math.PI / 2);
      });
    };
    return { update: updateFn, type: 'city' };
  }

  function buildParticleScene(params) {
    clearScene();
    const scene = getScene();
    addLights(scene);
    addGround(scene, 20);
    camera.position.set(0, 18, 12);
    camera.lookAt(0, 0, 0);

    const n = params.particles || 500;
    const geo = new THREE.BufferGeometry();
    const positions = new Float32Array(n * 3);
    const colors = new Float32Array(n * 3);
    const velocities = [];
    const colorPalette = [new THREE.Color(0x00e5ff), new THREE.Color(0xff4d6d),
      new THREE.Color(0x00ffa3), new THREE.Color(0xc084fc)];
    for (let i = 0; i < n; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 14;
      positions[i * 3 + 1] = Math.random() * 3;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 14;
      const c = colorPalette[Math.floor(Math.random() * colorPalette.length)];
      colors[i * 3] = c.r; colors[i * 3 + 1] = c.g; colors[i * 3 + 2] = c.b;
      velocities.push(new THREE.Vector3((Math.random() - 0.5) * 0.02, 0, (Math.random() - 0.5) * 0.02));
    }
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    const points = new THREE.Points(geo, new THREE.PointsMaterial({
      size: 0.2, vertexColors: true, transparent: true, opacity: 0.95,
      blending: THREE.AdditiveBlending, sizeAttenuation: true
    }));
    scene.add(points);

    const updateFn = (t, dt) => {
      const pos = geo.attributes.position.array;
      for (let i = 0; i < n; i++) {
        pos[i * 3] += velocities[i].x;
        pos[i * 3 + 2] += velocities[i].z;
        if (Math.abs(pos[i * 3]) > 7) velocities[i].x *= -1;
        if (Math.abs(pos[i * 3 + 2]) > 7) velocities[i].z *= -1;
        pos[i * 3 + 1] = 1 + Math.sin(t * 0.5 + i * 0.01) * 0.5;
      }
      geo.attributes.position.needsUpdate = true;
      const angle = t * 0.1;
      camera.position.x = Math.sin(angle) * 15;
      camera.position.z = Math.cos(angle) * 15;
      camera.lookAt(0, 1, 0);
    };
    return { update: updateFn, type: 'particles' };
  }

  function buildNetworkScene(params) {
    clearScene();
    const scene = getScene();
    addLights(scene);
    camera.position.set(0, 15, 16);
    camera.lookAt(0, 0, 0);

    const n = params.nodes || 80;
    const nodes = [];
    const nodeGeo = new THREE.SphereGeometry(0.2, 8, 8);
    const nodeGroup = new THREE.Group();
    const hubMat = new THREE.MeshBasicMaterial({ color: 0xc084fc });
    const normalMat = new THREE.MeshBasicMaterial({ color: 0x00e5ff });
    for (let i = 0; i < n; i++) {
      const phi = Math.acos(1 - 2 * (i + 0.5) / n);
      const theta = Math.PI * (1 + Math.sqrt(5)) * i;
      const r = 5 + Math.random() * 2;
      const x = r * Math.sin(phi) * Math.cos(theta);
      const y = r * Math.cos(phi);
      const z = r * Math.sin(phi) * Math.sin(theta);
      const isHub = i % 8 === 0;
      const mesh = new THREE.Mesh(nodeGeo, isHub ? hubMat : normalMat);
      mesh.scale.setScalar(isHub ? 3 : 1.5);
      mesh.position.set(x, y, z);
      nodeGroup.add(mesh);
      nodes.push({ mesh, x, y, z, isHub, phase: Math.random() * 6 });
    }
    scene.add(nodeGroup);
    const lineMat = new THREE.LineBasicMaterial({ color: 0x1b4a6b, transparent: true, opacity: 0.3 });
    for (let i = 0; i < n; i++) {
      const connections = 2 + Math.floor(Math.random() * 3);
      for (let c = 0; c < connections; c++) {
        const j = Math.floor(Math.random() * n);
        if (i !== j) {
          const geo = new THREE.BufferGeometry().setFromPoints([
            new THREE.Vector3(nodes[i].x, nodes[i].y, nodes[i].z),
            new THREE.Vector3(nodes[j].x, nodes[j].y, nodes[j].z)]);
          scene.add(new THREE.Line(geo, lineMat));
        }
      }
    }
    const updateFn = (t, dt) => {
      const angle = t * 0.08;
      camera.position.x = Math.sin(angle) * 20;
      camera.position.z = Math.cos(angle) * 20;
      camera.position.y = 8 + Math.sin(t * 0.15) * 4;
      camera.lookAt(0, 0, 0);
      nodes.forEach(nd => { nd.mesh.position.y = nd.y + Math.sin(t * 0.8 + nd.phase) * 0.15; });
    };
    return { update: updateFn, type: 'network' };
  }

  function buildWaveScene(params) {
    clearScene();
    const scene = getScene();
    addLights(scene);
    camera.position.set(0, 18, 16);
    camera.lookAt(0, 0, 0);
    const size = 40, seg = 40;
    const geo = new THREE.PlaneGeometry(size, size, seg, seg);
    const mat = new THREE.MeshPhongMaterial({ color: 0x00e5ff, wireframe: true, transparent: true, opacity: 0.7, side: THREE.DoubleSide });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.rotation.x = -Math.PI / 2;
    scene.add(mesh);
    const base = geo.attributes.position.array.slice();
    const updateFn = (t, dt) => {
      const pos = geo.attributes.position.array;
      for (let i = 0; i < pos.length; i += 3) {
        const x = base[i], y = base[i + 1];
        pos[i + 2] = Math.sin(x * 0.3 + t * 1.5) * 0.8 + Math.cos(y * 0.4 + t * 1.2) * 0.6 + Math.sin((x + y) * 0.2 + t * 0.8) * 0.4;
      }
      geo.attributes.position.needsUpdate = true;
      geo.computeVertexNormals();
    };
    return { update: updateFn, type: 'waves' };
  }

  function buildTerrainScene(params) {
    clearScene();
    const scene = getScene();
    addLights(scene);
    camera.position.set(14, 14, 14);
    camera.lookAt(0, 0, 0);
    const size = 30, seg = 30;
    const geo = new THREE.PlaneGeometry(size, size, seg, seg);
    const colors = [];
    const pos = geo.attributes.position.array;
    for (let i = 0; i < pos.length; i += 3) {
      const h = Math.random() * 2;
      pos[i + 2] = h;
      if (h > 1.4) colors.push(0.4, 1.0, 0.4);
      else if (h > 0.7) colors.push(0.9, 0.9, 0.3);
      else colors.push(0.2, 0.4, 0.8);
    }
    geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(colors), 3));
    geo.computeVertexNormals();
    const mat = new THREE.MeshPhongMaterial({ vertexColors: true, wireframe: false, transparent: true, opacity: 0.95, flatShading: true });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.rotation.x = -Math.PI / 2;
    scene.add(mesh);
    const agentGeo = new THREE.SphereGeometry(0.15, 6, 6);
    const agentMat = new THREE.MeshBasicMaterial({ color: 0xff4d6d });
    const agents = [];
    for (let i = 0; i < 30; i++) {
      const m = new THREE.Mesh(agentGeo, agentMat);
      m.position.set((Math.random() - 0.5) * size, 1, (Math.random() - 0.5) * size);
      scene.add(m);
      agents.push(m);
    }
    const updateFn = (t, dt) => {
      const angle = t * 0.06;
      camera.position.x = Math.sin(angle) * 18;
      camera.position.z = Math.cos(angle) * 18;
      camera.lookAt(0, 0, 0);
      agents.forEach((m, i) => { m.position.y = 1.5 + Math.sin(t * 0.5 + i) * 0.3; });
      const posArr = geo.attributes.position.array;
      for (let i = 0; i < posArr.length; i += 3) {
        posArr[i + 2] = Math.sin(posArr[i] * 0.2 + t * 0.3) * 0.5 + Math.cos(posArr[i + 1] * 0.15 + t * 0.2) * 0.5;
      }
      geo.attributes.position.needsUpdate = true;
    };
    return { update: updateFn, type: 'terrain' };
  }

  const sceneBuilders = {
    city: buildCityScene,
    particles: buildParticleScene,
    network: buildNetworkScene,
    waves: buildWaveScene,
    terrain: buildTerrainScene
  };

  function switchScene(type, params = {}) {
    const builder = sceneBuilders[type];
    if (!builder) return;
    const hud = document.getElementById('viz3dHud');
    if (hud) hud.remove();
    window._vizData = null;   // 演示场景不带模型数据，防热力强度用旧值
    currentScene = builder(params);
  }

  function autoDetect(modelId) {
    if (!modelId) { switchScene('city'); return; }
    const prefix = modelId.replace(/[0-9]+$/, '').toUpperCase();
    const map = {
      'NET': 'network', 'BEH': 'particles',
      'ECO': 'waves', 'SYS': 'waves',
      'APP': 'city', 'MET': 'particles'
    };
    if (/NET(09[5-9]|1[01][0-9])/.test(modelId)) { switchScene('city'); return; }
    if (/NET(05[1-9]|06[0-9])/.test(modelId)) { switchScene('particles'); return; }
    if (/BEH(001|002|003|004)/.test(modelId)) { switchScene('terrain'); return; }
    if (/ECO(11[0-5])/.test(modelId)) { switchScene('terrain'); return; }
    switchScene(map[prefix] || 'city');
  }

  function pause() {
    isRunning = false;stopAnimation();frameCounter=0;rateSince=0;
    const badge=document.getElementById('fps');
    if (badge) badge.textContent='已暂停';
  }
  function resume() { if (!isRunning) clock.start();isRunning = true;scheduleAnimation(); }

  // ============================================================
  // WP7 状态同源沙盘：实体帧驱动渲染（真实模型状态，禁随机漫游）
  // provenance=entity → 主体位置/状态逐帧来自模型计算；
  // provenance=aggregate → 用已知模型机制映射汇总观测。
  // ============================================================
  window._vizStateStream = null;
  window._vizStateIdx = -1;
  let selectedStateEntity = '';
  let followingStateEntity = '';
  let stateCameraOverview = true;
  const sceneLayers = {base:true,entities:true,roads:true,facilities:true,labels:true,events:true};
  let studioProfile = null, studioStage = null;
  const overviewTarget = new THREE.Vector3();
  const viewTarget = new THREE.Vector3();
  let cameraPreset='fit',viewHull=[],viewFitRadius=50,cameraMotion=0;
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  let stateSmoothing = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  reduced.addEventListener('change',e=>{window.DAYAN3D.setSmoothing(!e.matches);if(e.matches)stopCameraMotion();});
  function measureWorld(stream) {
    const kind=studioProfile.kind, frames=stream.frames||[], first=frames[0]||{};
    const extent=studioStage.userData.extent;
    if(extent){
      const heights=first.space?.vertical_bounds?.map(z=>z*DAYAN_SCENE_STUDIO.scaleFor(first))||[0];
      return heights.flatMap(y=>[-1,1].flatMap(x=>[-1,1].map(z=>new THREE.Vector3(x*extent.width/2,y,z*extent.depth/2))));
    }
    if(['ring-road','queue'].includes(kind)){
      const radius=kind==='ring-road'?34:studioStage.userData.radius||24;
      return Array.from({length:48},(_,i)=>{
        const angle=i/48*Math.PI*2;
        return new THREE.Vector3(Math.cos(angle)*radius,0,Math.sin(angle)*radius);
      });
    }
    const points=[];
    const add=(x,y,frame)=>{
      if(Number.isFinite(x)&&Number.isFinite(y))points.push(stateWorldXY({x,y},frame));
    };
    for(const f of first.facilities||[]){
      if(f.type==='road_network'){
        for(const segment of f.segments||[])for(const [x,y] of segment)add(x,y,first);
      }else if(Number.isFinite(f.width)&&Number.isFinite(f.depth)){
        for(const dx of [-.5,.5])for(const dy of [-.5,.5])add(f.x+f.width*dx,f.y+f.depth*dy,first);
      }else add(f.x,f.y,first);
    }
    const stride=Math.max(1,Math.ceil(frames.length/20));
    for(let i=0;i<frames.length;i++){
      if(i%stride&&i!==frames.length-1)continue;
      const frame=frames[i];
      for(const e of frame.entities||[])if(Number.isFinite(e.x)&&Number.isFinite(e.y))points.push(stateWorldXY(e,frame));
    }
    if(!points.length)return [new THREE.Vector3(-16,0,-11),new THREE.Vector3(16,0,11)];
    // Directional extremes bound the observed footprint without retaining every point.
    const boundary=[];
    for(let i=0;i<96;i++){
      const angle=i/96*Math.PI*2, x=Math.cos(angle), z=Math.sin(angle);
      let far=-Infinity,point=points[0];
      for(const p of points){
        const projection=x*p[0]+z*p[2];
        if(projection>far){far=projection;point=p;}
      }
      boundary.push(new THREE.Vector3(point[0],0,point[2]));
    }
    return boundary;
  }
  function fitPose() {
    const box=new THREE.Box3().setFromPoints(viewHull);
    const target=box.getCenter(new THREE.Vector3());
    const size=box.getSize(new THREE.Vector3());
    viewFitRadius=Math.max(10,size.length());
    const vertical=Math.tan(camera.fov*Math.PI/360), horizontal=vertical*Math.max(.18,camera.aspect);
    const geographic=studioProfile.kind==='geographic';
    const presets=cameraPreset==='plan'?[[0,1.562]]:cameraPreset==='low'?[[.62,.47]]:
      geographic?Array.from({length:12},(_,i)=>[i*Math.PI/6,.89]):[[.39,.96]];
    let best, quality=-Infinity;
    for(const [yaw,pitch] of presets){
      const direction=new THREE.Vector3(Math.sin(yaw)*Math.cos(pitch),Math.sin(pitch),Math.cos(yaw)*Math.cos(pitch));
      const right=new THREE.Vector3(0,1,0).cross(direction).normalize();
      const up=direction.clone().cross(right);
      const coords=viewHull.map(point=>{
        const delta=point.clone().sub(target);
        return [delta.dot(right),delta.dot(up),delta.dot(direction)];
      });
      const distance=Math.max(10,...coords.map(([x,y,z])=>z+Math.max(Math.abs(x)/(horizontal*.91),Math.abs(y)/(vertical*.84))))+1;
      const projected=coords.map(([x,y,z])=>[x/((distance-z)*horizontal),y/((distance-z)*vertical)]);
      const extent=axis=>Math.max(...projected.map(p=>p[axis]))-Math.min(...projected.map(p=>p[axis]));
      const area=extent(0)*extent(1);
      if(area>quality){quality=area;best={target,position:target.clone().addScaledVector(direction,distance)};}
    }
    return best;
  }
  function stopCameraMotion() {
    if(cameraMotion)cancelAnimationFrame(cameraMotion);
    cameraMotion=0;INTRO.active=false;
  }
  function moveCamera(position,target,smooth=false) {
    stopCameraMotion();
    if(!smooth||reduced.matches){
      viewTarget.copy(target);camera.position.copy(position);camera.lookAt(viewTarget);
      renderer.render(getScene(),camera);
      return;
    }
    const from=camera.position.clone(),startTarget=viewTarget.clone(),started=performance.now();
    const tick=now=>{
      const elapsed=Math.min(1,(now-started)/330),ease=1-(1-elapsed)**3;
      viewTarget.lerpVectors(startTarget,target,ease);
      camera.position.lerpVectors(from,position,ease);
      camera.lookAt(viewTarget);
      if(!isRunning)renderer.render(getScene(),camera);
      cameraMotion=elapsed<1&&!document.hidden?requestAnimationFrame(tick):0;
    };
    cameraMotion=requestAnimationFrame(tick);
  }
  function fitStateCamera(smooth=false) {
    if(!camera||!viewHull.length)return;
    const {position,target}=fitPose();
    overviewTarget.copy(target);
    moveCamera(position,target,smooth);
  }
  function stateEntityMesh(id) {
    const group=getScene().children.find(c=>c.userData?.isStateGroup),map=group?.userData.meshMap;
    if(!map)return;
    const numeric=Number(id);
    const direct=map.get(id)||((String(numeric)===id)&&map.get(numeric));
    if(direct)return direct;
    for(const [key,mesh] of map)if(String(key)===String(id))return mesh;
  }
  function reportPose() {
    document.dispatchEvent(new CustomEvent('dayan:camera-pose',{detail:stateCameraOverview?cameraPreset:'custom'}));
  }
  let hoveredEntity=null;
  function paintHover(id,e,render=true) {
    const host=document.getElementById('sceneHover');
    if(!host)return;
    const fr=window._vizStateStream?.frames[window._vizStateIdx];
    const group=getScene().children.find(c=>c.userData?.isStateGroup);
    const mesh=id===null?null:stateEntityMesh(id);
    const entity=mesh?.visible&&fr?.entities?.find(item=>String(item.id)===String(id));
    if(!entity){
      host.hidden=true;hoveredEntity=null;
      if(group?.userData.hoverRing?.visible){group.userData.hoverRing.visible=false;if(render&&!isRunning)renderer.render(getScene(),camera);}
      return;
    }
    hoveredEntity=id;
    if(!group.userData.hoverRing){
      const ring=new THREE.Mesh(new THREE.RingGeometry(.95,1.08,32),new THREE.MeshBasicMaterial({color:0xe8faff,side:THREE.DoubleSide,depthWrite:false}));
      ring.rotation.x=-Math.PI/2;group.add(ring);group.userData.hoverRing=ring;
    }
    const ring=group.userData.hoverRing;ring.visible=true;ring.position.set(mesh.position.x,.49,mesh.position.z);
    if(e){
      const rect=renderer.domElement.getBoundingClientRect();
      host.style.left=Math.max(8,Math.min(rect.width-202,e.clientX-rect.left+14))+'px';
      host.style.top=Math.max(8,Math.min(rect.height-78,e.clientY-rect.top+14))+'px';
    }
    const text=[String(entity.id),[entity.type,entity.state].filter(v=>v!==undefined).map(v=>DAYAN_ANALYSIS.label(String(v))).join(' · ')];
    if(Number.isFinite(entity.x)&&Number.isFinite(entity.y))text.push(`(${DAYAN_ANALYSIS.fmt(entity.x)}, ${DAYAN_ANALYSIS.fmt(entity.y)}) ${fr.space?.unit||''}`);
    host.textContent=text.join('\n');host.hidden=false;
    if(render&&!isRunning)renderer.render(getScene(),camera);
  }
  function applySceneLayer(object) {
    if(object.userData.spatialSuppressed){object.visible=false;return;}
    const layer=object.userData.sceneLayer;
    if(layer)object.visible=sceneLayers[layer];
  }
  function setSceneLayer(layer,value) {
    if(!Object.hasOwn(sceneLayers,layer))return;
    sceneLayers[layer]=Boolean(value);
    getScene().traverse(applySceneLayer);
    if(!sceneLayers.entities)paintHover(null,null,false);
    // Reapply the current frame to restore per-entity visibility and update instance counts.
    window.DAYAN3D.renderAt(window.DAYAN_RESULTS?.time||0);
  }
  function selectStateEntity(id,notify=false) {
    if(followingStateEntity){followingStateEntity='';document.dispatchEvent(new CustomEvent('dayan:camera-mode',{detail:{following:false}}));}
    selectedStateEntity=String(id||'');
    const group=getScene().children.find(c=>c.userData?.isStateGroup);
    group?.children.forEach(mesh=>{if(mesh.material?.emissive){mesh.material.emissive.setHex(String(mesh.userData.entityId)===selectedStateEntity?0x51decc:0x000000);mesh.material.emissiveIntensity=.65;}});
    syncStateInstances(group);
    if(notify&&id)document.dispatchEvent(new CustomEvent('dayan:entity-selected',{detail:{id:selectedStateEntity}}));
    if(renderer&&sceneObj)renderer.render(sceneObj,camera);
  }
  function focusStateEntity(id,smooth=true) {
    const mesh=stateEntityMesh(id);if(!mesh||!camera)return false;
    stateCameraOverview=false;reportPose();
    selectStateEntity(id);
    const target=mesh.position.clone(),offset=camera.position.clone().sub(viewTarget).normalize().multiplyScalar(Math.max(10,viewFitRadius*.29));
    moveCamera(target.clone().add(offset),target,smooth);
    return true;
  }
  function resetStateCamera() {
    followingStateEntity='';document.dispatchEvent(new CustomEvent('dayan:camera-mode',{detail:{following:false}}));
    stateCameraOverview=true;cameraPreset='fit';reportPose();if(!camera)return;fitStateCamera(true);
  }
  function followStateEntity(id,enabled=true) {
    if(enabled&&focusStateEntity(id,false)){followingStateEntity=String(id);document.dispatchEvent(new CustomEvent('dayan:camera-mode',{detail:{following:true}}));return true;}
    followingStateEntity='';document.dispatchEvent(new CustomEvent('dayan:camera-mode',{detail:{following:false}}));return false;
  }

  function stateMeshFor(ent) {
    return DAYAN_SCENE_STUDIO.entity(ent,studioProfile);
  }

  const displaySamples=new WeakMap();
  let displayPriorities=new Map();
  function displayEntities(frame) {
    const entities=(frame.entities||[]).filter(e=>DAYAN_SCENE_STUDIO.inSceneSpace(e,frame));if(entities.length<=3000)return entities;
    if(!displaySamples.has(frame)){
      const priority=id=>{
        let value=displayPriorities.get(id);
        if(value===undefined){
          let h=2166136261;for(const c of String(id))h=Math.imul(h^c.charCodeAt(0),16777619);
          value=h>>>0;displayPriorities.set(id,value);
        }
        return value;
      };
      displaySamples.set(frame,[...entities].sort((a,b)=>priority(a.id)-priority(b.id)||String(a.id).localeCompare(String(b.id))).slice(0,3000));
    }
    return displaySamples.get(frame);
  }

  const instanceColor=new THREE.Color();
  function syncStateInstances(group,includeColors=true,time=window._vizNow||0) {
    const people=group?.userData.people;
    if(people)DAYAN_SCENE_STUDIO.drawPeople(people,group.userData.meshMap,time,selectedStateEntity,reduced.matches);
    const batch=group?.userData.carBatch;if(!batch)return;
    const map=group.userData.meshMap;
    if(includeColors){
      const ids=[];
      map.forEach(m=>{
        if(!m.userData.instancedCar||!m.visible)return;
        instanceColor.setHex(String(m.userData.entityId)===selectedStateEntity?0x51decc:m.userData.stateColor);
        batch.setColorAt(ids.length,instanceColor);ids.push(m.userData.entityId);
      });
      batch.count=ids.length;batch.userData.instanceIds=ids;batch.instanceColor.needsUpdate=true;
    }
    batch.userData.instanceIds.forEach((id,i)=>{
      const mesh=map.get(id);mesh.updateMatrix();batch.setMatrixAt(i,mesh.matrix);
    });
    batch.instanceMatrix.needsUpdate=true;
  }

  function stateWorldXY(ent, fr) {
    // 模型坐标 → 场景坐标（按实体类型线性映射，保持真实相对位置）
    if (fr?.space?.bounds?.length === 4) {
      const [x0,y0,x1,y1]=fr.space.bounds, scale=70/Math.max(x1-x0,y1-y0,1e-9);
      return [(ent.x-(x0+x1)/2)*scale,0.7+(Number.isFinite(ent.z)?ent.z*scale:0),((y0+y1)/2-ent.y)*scale];
    }
    if (ent.type === "car") {
      // 环形道路 → 圆周轨道：cell index 等比映射为角度，速度仍控制颜色
      const len = (fr?.facilities||[]).find(f=>f.type==='road')?.length || 100;
      const R = 30;
      const ang = (ent.x / Math.max(1, len)) * Math.PI * 2;
      return [ Math.cos(ang) * R, 0.65, Math.sin(ang) * R ];
    }
    if (ent.type === "resident") {
      const size = (fr?.facilities||[]).find(f=>['grid','lattice'].includes(f.type))?.size || window._vizStateBounds?.size || 40;
      return [ (ent.x - size / 2) * (70 / size), 0.5, (ent.y - size / 2) * (70 / size) ];
    }
    if (ent.type === "pedestrian") {
      return [ (ent.x - 15) * 2.2, 0.85, (20 - ent.y) * 2.0 ];
    }
    if (ent.type === "server") {
      const span=window._vizStateBounds.queue||{center:1,scale:3.2};
      return [ (ent.x-span.center)*span.scale, 0.85, -4 ];
    }
    if (ent.type === "customer") {
      const span=window._vizStateBounds.queue||{center:0,scale:3.2};
      return [ (ent.x-span.center)*span.scale, 0.8, 3 ];
    }
    if (ent.type === "age_group") {
      return [ (ent.x - 1) * 6.0, 0, 0 ];
    }
    return [ ent.x || 0, 0.5, ent.y || 0 ];
  }
  function personGround(entity,frame){
    const floor=studioProfile.kind==='queue'?-.25:.115;
    return floor+(Number.isFinite(entity.z)?entity.z*DAYAN_SCENE_STUDIO.scaleFor(frame):0);
  }
  function adjacentFrames(){
    const stream=window._vizStateStream,index=window._vizStateIdx;
    const lookup=frame=>frame?{frame,entities:new Map((frame.entities||[]).map(entity=>[entity.id,entity]))}:null;
    return {previous:lookup(stream.preview?stream.previousFrame:stream.frames[index-1]),
      next:lookup(stream.frames[index+1])};
  }
  function personDirection(entity,position,neighbor,forward){
    const other=neighbor?.entities.get(entity.id);
    if(!Number.isFinite(other?.x)||!Number.isFinite(other?.y)||(other.type==='pedestrian'&&other.state==='exited'))return null;
    const [x,,z]=stateWorldXY(other,neighbor.frame);
    const dx=forward?x-position.x:position.x-x, dz=forward?z-position.z:position.z-z;
    const distance=Math.hypot(dx,dz);
    return distance>1e-5&&distance<=24?Math.atan2(dx,dz):null;
  }
  function applyPerson(model,entity,frame,neighbors) {
    const ahead=personDirection(entity,model.position,neighbors.next,true);
    const behind=personDirection(entity,model.position,neighbors.previous,false);
    const moving=entity.type==='pedestrian'&&Number.isFinite(entity.speed)
      ? entity.state!=='exited'&&entity.speed>1e-5 : (neighbors.next?ahead:behind)!==null;
    const info=model.userData;
    model.position.y=personGround(entity,frame);
    info.heading=ahead??behind??0;
    info.pose=DAYAN_SCENE_STUDIO.personPose(entity,studioProfile,moving);
    info.size=['m','米','meter','metre'].includes(frame.space?.unit)
      ? THREE.MathUtils.clamp(DAYAN_SCENE_STUDIO.scaleFor(frame),.8,3.3) : 1.25;
    if(frame.space?.vertical_bounds&&['m','米','meter','metre'].includes(frame.space.unit))
      info.size=DAYAN_SCENE_STUDIO.scaleFor(frame)*(Number.isFinite(entity.height)?entity.height:1.65)/1.565;
  }

  let stateOverlay = null;
  let eventMarker = null;
  function eventPosition(event,frame) {
    if(Number.isFinite(event.x)&&Number.isFinite(event.y))return event;
    const key=event.entity_id??(event.bus_id===undefined?null:'bus-'+event.bus_id);
    const entity=key===null?null:frame.entities?.find(e=>String(e.id)===String(key));
    return Number.isFinite(entity?.x)&&Number.isFinite(entity?.y)?entity:null;
  }
  function focusEvent(event) {
    const frame=window._vizStateStream?.frames[window._vizStateIdx];
    const point=frame&&eventPosition(event,frame);
    if(!point||!sceneLayers.events||event.applied===false)return false;
    if(!eventMarker){
      eventMarker=new THREE.Mesh(new THREE.RingGeometry(1.45,1.8,40),new THREE.MeshBasicMaterial({color:0xffd486,side:THREE.DoubleSide}));
      eventMarker.rotation.x=-Math.PI/2;eventMarker.userData.sceneLayer='events';getScene().add(eventMarker);
    }
    const [x,,z]=stateWorldXY(point,frame), target=new THREE.Vector3(x,.58,z);
    eventMarker.position.copy(target);eventMarker.visible=true;eventMarker.userData.eventTime=event.sim_t;
    if(followingStateEntity)followStateEntity('',false);
    stateCameraOverview=false;reportPose();
    const offset=camera.position.clone().sub(viewTarget).normalize().multiplyScalar(Math.max(11,viewFitRadius*.42));
    moveCamera(target.clone().add(offset),target,true);return true;
  }
  function paintStateOverlay(frame) {
    if (stateOverlay?.parent) {stateOverlay.parent.remove(stateOverlay);disposeDeep(stateOverlay);}
    stateOverlay = null;
    const annotated = document.getElementById('layerReadout');
    if (annotated) annotated.hidden = true;
    if (layerFxMode === 'flow' || window._vizStateStream?.preview) return;
    const positioned = (frame.entities || []).filter(e=>Number.isFinite(e.x)&&Number.isFinite(e.y));
    const positions = [], colors = [];
    let label = '';
    if(layerFxMode==='roadFlow'&&studioProfile.kind==='ring-road'&&Number.isFinite(frame.aggregates?.flux)){
      let low=Infinity,high=-Infinity;
      for(const row of window._vizStateStream.observations||[])if(Number.isFinite(row.flux)){low=Math.min(low,row.flux);high=Math.max(high,row.flux);}
      const value=frame.aggregates.flux, fraction=high>low?THREE.MathUtils.clamp((value-low)/(high-low),0,1):.5;
      const color=new THREE.Color(0x4e9acc).lerp(new THREE.Color(0xf6b75b),fraction);
      stateOverlay=new THREE.Mesh(new THREE.RingGeometry(28.8,31.2,160),new THREE.MeshBasicMaterial({color,transparent:true,opacity:.66,side:THREE.DoubleSide,depthWrite:false}));
      stateOverlay.rotation.x=-Math.PI/2;stateOverlay.position.y=.215;getScene().add(stateOverlay);
      if(annotated){annotated.textContent=`整条环路归档通量 ${DAYAN_ANALYSIS.fmt(value)} · 冷色低 / 暖色高 · t=${frame.sim_t}`;annotated.hidden=false;}
      return;
    }
    if (layerFxMode === 'heat' && positioned.length) {
      const counts = new Map(), cell = 4;
      for (const entity of positioned) {
        const [x,,z]=stateWorldXY(entity,frame);
        const key=[Math.floor(x/cell),Math.floor(z/cell)].join(',');
        counts.set(key,(counts.get(key)||0)+1);
      }
      const maximum=Math.max(...counts.values());
      for (const [key,count] of counts) {
        const [x,z]=key.split(',').map(axis=>Number(axis)*cell), x2=x+cell*.91, z2=z+cell*.91;
        const color = new THREE.Color().lerpColors(new THREE.Color(0x21657b),new THREE.Color(0xffbc68),Math.sqrt(count/maximum));
        positions.push(x,.12,z,x2,.12,z,x2,.12,z2,x,.12,z,x2,.12,z2,x,.12,z2);
        for(let i=0;i<6;i++) colors.push(color.r,color.g,color.b);
      }
      label = `投影网格主体数 · 冷色低 / 暖色高 · 每格最大 ${maximum} · t=${frame.sim_t}`;
    } else if (layerFxMode === 'network') {
      const points=new Map(positioned.map(e=>[String(e.id),stateWorldXY(e,frame)]));
      let count=0;
      for (const edge of frame.relations || []) {
        const a=points.get(String(edge.source)), b=points.get(String(edge.target));
        if (!a || !b) continue;
        positions.push(a[0],.82,a[2],b[0],.82,b[2]);count++;
        if (edge.directed) {
          const angle=Math.atan2(b[2]-a[2],b[0]-a[0]);
          for(const offset of [-.4,.4]) positions.push(b[0],.82,b[2],b[0]-.8*Math.cos(angle+offset),.82,b[2]-.8*Math.sin(angle+offset));
        }
      }
      if (count) label=`模型记录的关系 ${count} 条 · 箭头指向边的目标 · t=${frame.sim_t}`;
    } else if (layerFxMode === 'trajectory') {
      const stream=window._vizStateStream, id=String(window.DAYAN_RESULTS?.entityId || '');
      const last=window._vizStateIdx;
      let previous=null, count=0;
      for (const f of stream.frames.slice(Math.max(0,last-99),last+1)) {
        const e=f.entities?.find(e=>String(e.id)===id&&Number.isFinite(e.x)&&Number.isFinite(e.y));
        const point=e?stateWorldXY(e,f):null;
        if (point && previous) {positions.push(previous[0],.86,previous[2],point[0],.86,point[2]);count++;}
        previous=point;
      }
      if (count) label=`主体 ${id} · ${count} 段相邻有记录轨迹 · t≤${frame.sim_t}`;
    }
    if (!positions.length) return;
    const geometry=new THREE.BufferGeometry();
    geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
    if (colors.length) {
      geometry.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));
      stateOverlay=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({vertexColors:true,transparent:true,opacity:.58,side:THREE.DoubleSide,depthWrite:false}));
    } else stateOverlay=new THREE.LineSegments(geometry,new THREE.LineBasicMaterial({color:0x9cf2ec,transparent:true,opacity:.84}));
    getScene().add(stateOverlay);
    if (annotated) {annotated.textContent=label;annotated.hidden=!label;}
  }

  function vizApplyFrame(fr) {
    if(studioProfile.kind==='observations')return;
    const scene = getScene();
    let group = scene.children.find(c => c.userData && c.userData.isStateGroup);
    if (!group) {
      group = new THREE.Group();
      group.userData.isStateGroup = true;
      scene.add(group);
    }
    const meshMap = group.userData.meshMap = group.userData.meshMap || new Map();
    const seen = new Set((fr.facilities||[]).map(f=>"fac_"+f.id));
    let neighbors;
    displayEntities(fr).forEach(ent => {
      if(ent.type==='age_group'||!Number.isFinite(ent.x)||
         (!Number.isFinite(ent.y)&&!['ring-road','queue'].includes(studioProfile.kind)))return;
      seen.add(ent.id);
      let m = meshMap.get(ent.id);
      if (!m) {
        if(studioProfile.kind==='ring-road'&&!studioProfile.rich&&ent.type==='car'){
          if(!group.userData.carBatch){
            const template=stateMeshFor(ent);template.material.color.setHex(0xffffff);
            // At this density each vehicle is a few pixels wide. Retain its
            // dimensions/color/pose with a shared 12-triangle body instead of
            // thousands of independently bevelled meshes and shadow casters.
            template.geometry.dispose();
            const batch=new THREE.InstancedMesh(new THREE.BoxGeometry(1.55,.42,.85),template.material,3000);
            batch.castShadow=true;batch.receiveShadow=true;batch.frustumCulled=false;
            // Vehicles stay within the same world-space ring at every step.
            batch.boundingSphere=new THREE.Sphere(new THREE.Vector3(0,.65,0),32);
            batch.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
            batch.userData.sceneLayer='entities';applySceneLayer(batch);
            group.userData.carBatch=batch;group.add(batch);
          }
          m=new THREE.Object3D();m.userData.instancedCar=true;m.userData.glyph='vehicle';
        }else if(DAYAN_SCENE_STUDIO.isPerson(ent,studioProfile)){
          if(!group.userData.people){
            const batch=DAYAN_SCENE_STUDIO.peopleBatch(group,studioProfile.rich);
            for(const part of batch.parts)applySceneLayer(part.instances);
            group.userData.people=batch;
          }
          m=new THREE.Object3D();
          m.userData.person=true;
          const id=String(ent.id);
          m.userData.phase=[...id].reduce((value,letter)=>(value*31+letter.charCodeAt(0))%53,0)/53*Math.PI*2;
        }else m = stateMeshFor(ent);
        m.userData.entityId=ent.id;
        meshMap.set(ent.id, m);
        group.add(m);m.traverse(applySceneLayer);
      }
      const [x, y, z] = stateWorldXY(ent, fr);
      if (m.userData.pinBottom) {
        m.position.set(x, (m.geometry.parameters ? (m.geometry.parameters.height || 1) / 2 : y), z);
      } else {
        m.position.set(x, y, z);
      }
      m.visible = sceneLayers.entities&&(String(ent.state) !== "exited" || ent.type !== "pedestrian");
      if(m.userData.person){
        neighbors||=adjacentFrames();
        applyPerson(m,ent,fr,neighbors);
      }
      const stateColor=DAYAN_SCENE_STUDIO.color(ent,studioProfile);
      if(m.userData.instancedCar||m.userData.person)m.userData.stateColor=stateColor;
      if(m.material?.color)m.material.color.set(stateColor);
      m.children.forEach(part=>{if(part.userData.stateColor)part.material.color.set(stateColor);});
      if(studioProfile.kind==='ring-road'&&m.userData.glyph==='vehicle'){
        const length=(fr.facilities||[]).find(f=>f.type==='road')?.length||100;
        m.rotation.y=-(ent.x/length*Math.PI*2)-Math.PI/2;
        if(m.userData.instancedCar)m.scale.x=Math.min(1,Math.PI*60/length*.85/1.55);
      }
      if(m.material?.emissive){m.material.emissive.setHex(String(ent.id)===selectedStateEntity?0x51decc:0x000000);m.material.emissiveIntensity=.65;}
      if (ent.type === "server" && m.material?.color) {
        m.material.color.setHex(ent.state === "busy" ? 0xffb74d : 0x3a4a5a);
      }
    });
    DAYAN_SCENE_STUDIO.resizeGround(studioStage,fr);
    DAYAN_SPATIAL.update(studioStage,fr,applySceneLayer);
    updateEntityFX(group, fr);
    meshMap.forEach((m, id) => {
      if (!seen.has(id)) { group.remove(m); disposeDeep(m); meshMap.delete(id); }
    });
    // 设施：出口/道路指示
    (fr.facilities || []).forEach(f => {
      const fid = "fac_" + f.id;
      if([...(fr.space?.floors||[]),...(fr.space?.connectors||[])].some(geometry=>geometry.id===f.id)){
        const duplicate=meshMap.get(fid);
        if(duplicate){group.remove(duplicate);disposeDeep(duplicate);meshMap.delete(fid);}
        return; // The same actual ID already has its authoritative 3D geometry.
      }
      if(f.type==='model_facility'){
        let fm=meshMap.get(fid);
        if(!fm){fm=DAYAN_SCENE_STUDIO.facility(f);fm.userData.sceneLayer=f.kind==='road'?'roads':'facilities';fm.traverse(applySceneLayer);group.add(fm);meshMap.set(fid,fm);}
        DAYAN_SCENE_STUDIO.updateFacility(fm,f,fr,stateWorldXY);return;
      }
      if (!meshMap.has(fid)) {
        let fm = null;
        if (f.type === "road_network") {
          const positions=[];
          for(const segment of f.segments||[])for(const point of segment){const [x,y,z]=stateWorldXY({x:point[0],y:point[1]},fr);positions.push(x,.08,z);}
          const geometry=new THREE.BufferGeometry();geometry.setAttribute("position",new THREE.Float32BufferAttribute(positions,3));
          fm=new THREE.LineSegments(geometry,new THREE.LineBasicMaterial({color:0x9ce9e8,transparent:true,opacity:.82,toneMapped:false}));
        } else if(f.type === "assumed_pickup") {
          fm=new THREE.Mesh(new THREE.BoxGeometry(2.5,.5,2.5),new THREE.MeshStandardMaterial({color:0x7dbee7,emissive:0x1b4a77}));
        } else if(f.type === "assumed_shelter") {
          fm=new THREE.Mesh(new THREE.ConeGeometry(1.3,3,8),new THREE.MeshStandardMaterial({color:0xf5bd57}));
        } else if (f.type === "exit") {
          fm = new THREE.Mesh(new THREE.BoxGeometry(6, 0.3, 1.2),
            new THREE.MeshStandardMaterial({ color: 0x00ffa3, emissive: 0x00aa70, emissiveIntensity: 0.6 }));
        } else if (f.type === "counter") {
          fm = new THREE.Mesh(new THREE.BoxGeometry(10, 0.18, 2),
            new THREE.MeshStandardMaterial({ color: 0x2a3a4a }));
        }
        if (fm) {
          if (f.type === "exit" || f.type === "assumed_shelter" || f.type === "assumed_pickup") {
            const [fx, , fz] = stateWorldXY({ ...f, type: "pedestrian" }, fr);
            fm.position.set(fx, 0.1, fz);
          } else if(f.type!=="road_network") {
            fm.position.set(0, 0.1, -4);
          }
          fm.userData.sceneLayer=f.type==='road_network'?'roads':'facilities';applySceneLayer(fm);group.add(fm);
          meshMap.set(fid, fm);
        }
      }
    });
    paintStateOverlay(fr);
  }

  function buildStateLegend() {
    let box=document.getElementById('sceneLegend');
    if(!box){box=document.createElement('div');box.id='sceneLegend';container.appendChild(box);}
    box.replaceChildren();
    box.hidden=studioProfile.kind==='observations';
    if(box.hidden)return;
    const heading=document.createElement('strong');heading.textContent=studioProfile.title;box.appendChild(heading);
    if(studioProfile.kind==='geographic'){
      const bounds=window._vizStateStream?.frames?.[0]?.space?.bounds;
      if(bounds){
        const extent=document.createElement('span');extent.className='scene-extent';
        extent.textContent=`${Math.round(bounds[2]-bounds[0])} × ${Math.round(bounds[3]-bounds[1])} m`;
        heading.appendChild(extent);
      }
    }
    const items=document.createElement('div');items.className='scene-legend-items';
    DAYAN_SCENE_STUDIO.legend(studioProfile).forEach(item=>{const line=document.createElement('span'),dot=document.createElement('i');dot.style.background='#'+item.color.toString(16).padStart(6,'0');line.appendChild(dot);line.appendChild(document.createTextNode(item.text));items.appendChild(line);});box.appendChild(items);
    if(studioProfile.kind!=='observations'){
      const label=document.createElement('label');label.className='scene-smoothing';
      const input=document.createElement('input');input.type='checkbox';input.id='sceneSmoothing';input.checked=stateSmoothing;input.addEventListener('change',()=>DAYAN3D.setSmoothing(input.checked));
      label.append(input,document.createTextNode('帧间插值'));label.title='仅在相邻归档位置间做视觉插值；统计、主体详情与导出仍为原始帧。关闭可查看精确状态。';box.appendChild(label);
    }
  }

  let smoothNext=null, smoothPositions=null;
  function interpolateState(t,idx) {
    const frames=window._vizStateStream?.frames,fr=frames?.[idx],next=frames?.[idx+1];
    if(!stateSmoothing||!next||studioProfile.kind==='observations')return false;
    const span=next.sim_t-fr.sim_t,alpha=span>0?THREE.MathUtils.clamp((t-fr.sim_t)/span,0,1):0;
    if(!alpha)return false;
    if(smoothNext!==next){smoothNext=next;smoothPositions=new Map((next.entities||[]).map(e=>[e.id,e]));}
    const meshes=getScene().children.find(c=>c.userData?.isStateGroup)?.userData.meshMap;
    for(const e of displayEntities(fr)){
      const m=meshes?.get(e.id),n=smoothPositions.get(e.id);if(!m||!n||n.type!==e.type||!m.visible)continue;
      if(studioProfile.kind==='ring-road'&&e.type==='car'){
        const length=(fr.facilities||[]).find(f=>f.type==='road')?.length||100,delta=((n.x-e.x)%length+length)%length;
        if(delta>length/2)continue; // Ambiguous large jumps are left at the saved position.
        const at=e.x+delta*alpha,angle=at/length*Math.PI*2;
        m.position.set(Math.cos(angle)*30,.65,Math.sin(angle)*30);m.rotation.y=-angle-Math.PI/2;
      }else{
        const a=stateWorldXY(e,fr),b=stateWorldXY(n,next);
        if(Math.hypot(b[0]-a[0],b[2]-a[2])>24)continue; // No invented path across a teleport/wrap boundary.
        const fromY=m.userData.person?personGround(e,fr):a[1], toY=m.userData.person?personGround(n,next):b[1];
        m.position.set(a[0]+(b[0]-a[0])*alpha,fromY+(toY-fromY)*alpha,a[2]+(b[2]-a[2])*alpha);
        if(m.userData.glyph==='vehicle'&&Math.hypot(b[0]-a[0],b[2]-a[2])>1e-6)m.rotation.y=Math.atan2(-(b[2]-a[2]),b[0]-a[0]);
      }
    }
    return true;
  }

  function stateHud() {
    const canvas = renderer && renderer.domElement;
    const host = canvas ? canvas.parentElement : null;
    if (!host) return null;
    let hud = document.getElementById("vizStateHud");
    if (!hud) {
      hud = document.createElement("div");
      hud.id = "vizStateHud";
      hud.style.cssText = "position:absolute;left:10px;top:8px;z-index:5;font:10px monospace;" +
        "padding:4px 9px;border-radius:4px;background:rgba(4,7,15,.72);border:1px solid rgba(0,229,255,.35);color:#d8e2f2;pointer-events:none";
      host.appendChild(hud);
    }
    return hud;
  }

  function vizStateUpdate(t) {
    const st = window._vizStateStream;
    if (!st || !st.frames || !st.frames.length) return;
    if(eventMarker)eventMarker.visible=sceneLayers.events&&Math.abs(eventMarker.userData.eventTime-t)<1e-8;
    const n = st.frames.length;
    let idx;
    if(window.DAYAN_RESULTS?.active){
      let lo=0,hi=n;while(lo<hi){const m=(lo+hi)>>>1;if((st.frames[m].sim_t??0)<=t+1e-9)lo=m+1;else hi=m;}idx=Math.max(0,lo-1);
    }else{const DUR=Math.max(12,Math.min(30,n*1.4));idx=Math.min(n-1,Math.floor((t%DUR)/DUR*n));}
    const previous=followingStateEntity?stateEntityMesh(followingStateEntity)?.position.clone():null;
    const changed=idx!==window._vizStateIdx;
    if (changed) {
      const prevFr = st.frames[window._vizStateIdx];
      window._vizStateIdx = idx;
      vizApplyFrame(st.frames[idx]);
      if (prevFr&&studioProfile.kind!=='observations') spawnEventWaves(st, prevFr, st.frames[idx]);
      const hud = stateHud();
      if (hud) {
        const f = st.frames[idx];
        const entN = (f.entities || []).length;
        const source=studioProfile.kind==='observations'?'汇总观测':'场地与主体状态来自模型';
        hud.textContent = (st.preview ? '实时取样 · ' : st.partial ? '归档预览 · ' : '')+source
          + " · " + (st.model_id || "") + " · sim_t=" + (f.sim_t != null ? (+f.sim_t).toFixed(2) : "?")
          + (st.provenance === "entity" ? " · 实体 " + entN : "");
        if(st.provenance==="entity"&&entN>3000)hud.textContent+=st.partial?' · 视图采样3000':' · 视图采样3000；全量状态可导出';
        hud.style.borderColor = st.provenance === "entity"
          ? "rgba(0,255,163,.45)" : "rgba(255,183,77,.45)";
      }
    }
    const interpolated=interpolateState(t,idx);
    if(changed||interpolated)syncStateInstances(getScene().children.find(c=>c.userData?.isStateGroup),changed,t);
    if(changed&&hoveredEntity!==null)paintHover(hoveredEntity,null,false);
    if(previous&&followingStateEntity){const mesh=stateEntityMesh(followingStateEntity);if(mesh?.visible){camera.position.add(mesh.position.clone().sub(previous));viewTarget.copy(mesh.position);camera.lookAt(viewTarget);}else followStateEntity('',false);}
  }

  function visualizeState(stream,profile=null) {
    stopCameraMotion();
    paintHover(null,null,false);
    clearScene();
    stateOverlay=null;eventMarker=null;
    displayPriorities=new Map();smoothNext=null;smoothPositions=null;
    selectedStateEntity='';
    followingStateEntity='';
    stateCameraOverview=true;
    cameraPreset='fit';
    reportPose();
    window._vizStateStream = stream || null;
    window._vizStateIdx = -1;
    const firstEntities=stream?.frames?.[0]?.entities||[];
    window._vizStateBounds={size:firstEntities.reduce((size,e)=>Math.max(size,(e.x||0)+1,(e.y||0)+1),1)};
    const queuePositions=(stream?.frames||[]).flatMap(f=>(f.entities||[]).filter(e=>['server','customer'].includes(e.type)).map(e=>e.x));
    if(queuePositions.length){let lo=Infinity,hi=-Infinity;for(const x of queuePositions){lo=Math.min(lo,x);hi=Math.max(hi,x);}window._vizStateBounds.queue={center:(lo+hi)/2,scale:28/Math.max(10,hi-lo)};}
    const scene = getScene();
    studioProfile=profile||DAYAN_SCENE_STUDIO.resolve(stream);
    studioStage=DAYAN_SCENE_STUDIO.stage(scene,studioProfile,stream?.frames?.[0]||{});
    DAYAN_SPATIAL.update(studioStage,stream?.frames?.[0]||{},applySceneLayer);
    scene.traverse(applySceneLayer);
    viewHull=measureWorld(stream);
    renderer.toneMappingExposure=1.05;
    window._vizDarkness=0;
    INTRO.active=false;
    buildStateLegend();
    // 状态场景俯瞰机位：能同时读清环形/平面结构
    if (camera) {
      fitStateCamera();
      if(!stream?.preview)startIntroCinematic();
    }
    currentScene = { type: "state_" + ((stream && stream.provenance) || "aggregate"),
                     update: vizStateUpdate };
    // Saved-state worlds use their actual facilities; no synthetic weather is attached.
    return currentScene.type;
  }

  function completeArchive(stream) {
    const profile=DAYAN_SCENE_STUDIO.resolve(stream);
    if(window._vizStateStream?.run_id!==stream.run_id){visualizeState(stream,profile);return;}
    const id=selectedStateEntity,following=followingStateEntity,preset=cameraPreset,overview=stateCameraOverview;
    if(profile.kind!==studioProfile.kind||profile.rich!==studioProfile.rich||profile.glyph!==studioProfile.glyph||profile.kind==='queue'){
      const position=camera.position.clone(), target=viewTarget.clone();
      visualizeState(stream,profile);INTRO.active=false;
      stateCameraOverview=overview;cameraPreset=preset;
      if(overview)fitStateCamera();else moveCamera(position,target);
    }else{
      studioProfile=profile;window._vizStateStream=stream;window._vizStateIdx=-1;
      smoothNext=null;smoothPositions=null;
      viewHull=measureWorld(stream);buildStateLegend();
      if(overview&&profile.kind!=='ring-road')fitStateCamera();
    }
    selectedStateEntity=id;followingStateEntity=following;reportPose();
  }

  function clearSavedWorld() {
    stopCameraMotion();viewHull=[];
    paintHover(null,null,false);
    clearScene();studioProfile=null;studioStage=null;selectedStateEntity='';followingStateEntity='';
    displayPriorities=new Map();smoothNext=null;smoothPositions=null;
    window._vizStateStream=null;window._vizStateIdx=-1;stateOverlay=null;eventMarker=null;
    const annotated=document.getElementById('layerReadout');if(annotated) annotated.hidden=true;
    stateCameraOverview=true;currentScene=null;getScene().background=new THREE.Color(0x101f2e);
    if(renderer&&camera)renderer.render(getScene(),camera);
  }

  function preview(reading, first, previousFrame=null) {
    const frame=reading.frame;
    const sample={model_id:reading.model_id,frames:[frame],provenance:frame.provenance,preview:true,
      n_entities_max:reading.entities_total,previousFrame};
    const profile=DAYAN_SCENE_STUDIO.resolve(sample);
    if (first || !window._vizStateStream?.preview || profile.kind!==studioProfile?.kind||profile.glyph!==studioProfile?.glyph) visualizeState(sample,profile);
    else window._vizStateStream=sample;
    DAYAN3D.renderAt(frame.sim_t);
  }


  // ============================================================
  // 视觉增强层（2026-11-13）：
  //   A. 轻量泛光后处理（自研，无新依赖；失败自动降级直渲）
  //   B. 旧展示场景的昼夜循环
  //   C. 数据驱动特效：感染脉冲光环 / 疏散拖尾 / 干预冲击波
  //   D. 开场推近镜头（可交互打断）
  // 特效层只做视觉表现，不产生任何模型数据；provenance 标注不变。
  // ============================================================
  const POSTFX = { ready:false, enabled:false, userOn:true, costMs:0,
                   _avg:0, _frames:0, rtA:null, rtB:null, rtS:null,
                   camQuad:null, scBright:null, scBlur:null, scComp:null,
                   quad:null, sceneQuad:null };

  function initPostFX() {
    if (!renderer || POSTFX.ready || POSTFX.tried) return;
    POSTFX.tried = true;
    try {
      const size = renderer.getSize(new THREE.Vector2());
      const mkRT = (w, h, type) => new THREE.WebGLRenderTarget(
        Math.max(2, Math.floor(w)), Math.max(2, Math.floor(h)),
        { type: type, depthBuffer: true, stencilBuffer: false });
      const type = (renderer.capabilities.isWebGL2 &&
                    renderer.extensions.get('EXT_color_buffer_float'))
        ? THREE.HalfFloatType : THREE.UnsignedByteType;
      POSTFX.rtS = mkRT(size.x, size.y, type);
      POSTFX.rtA = mkRT(size.x / 4, size.y / 4, type);
      POSTFX.rtB = mkRT(size.x / 4, size.y / 4, type);
      POSTFX.scBright = new THREE.ShaderMaterial({
        uniforms: { tDiffuse: { value: null }, uThresh: { value: 0.68 } },
        vertexShader: POST_VERT, fragmentShader: POST_BRIGHT });
      POSTFX.scBlur = new THREE.ShaderMaterial({
        uniforms: { tDiffuse: { value: null }, uDir: { value: new THREE.Vector2(1, 0) },
                    uTexel: { value: new THREE.Vector2(1 / POSTFX.rtA.width, 1 / POSTFX.rtA.height) } },
        vertexShader: POST_VERT, fragmentShader: POST_BLUR });
      POSTFX.scComp = new THREE.ShaderMaterial({
        uniforms: { tScene: { value: null }, tBloom: { value: null },
                    uBloom: { value: 0.85 }, uVig: { value: 0.32 },
                    uSat: { value: 1.07 } },
        vertexShader: POST_VERT, fragmentShader: POST_COMP });
      POSTFX.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), POSTFX.scBright);
      POSTFX.sceneQuad = new THREE.Scene();
      POSTFX.camQuad = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
      POSTFX.sceneQuad.add(POSTFX.quad);
      POSTFX.ready = true;
      POSTFX.enabled = POSTFX.userOn;
      window.addEventListener('resize', () => resizePostFX());
    } catch (e) {
      console.warn('[viz3d] 后处理初始化失败，降级直渲:', e);
      POSTFX.ready = false; POSTFX.enabled = false;
    }
  }

  function resizePostFX() {
    if (!POSTFX.ready || !renderer) return;
    const size = renderer.getSize(new THREE.Vector2());
    [POSTFX.rtS, POSTFX.rtA, POSTFX.rtB].forEach(rt => rt.dispose());
    const type = POSTFX.rtS.texture.type;
    POSTFX.rtS = new THREE.WebGLRenderTarget(Math.max(2, size.x | 0), Math.max(2, size.y | 0), { type, depthBuffer: true });
    POSTFX.rtA = new THREE.WebGLRenderTarget(Math.max(2, size.x >> 2), Math.max(2, size.y >> 2), { type });
    POSTFX.rtB = new THREE.WebGLRenderTarget(Math.max(2, size.x >> 2), Math.max(2, size.y >> 2), { type });
    POSTFX.scBlur.uniforms.uTexel.value.set(1 / POSTFX.rtA.width, 1 / POSTFX.rtA.height);
  }

  function _fsQuad(mat) {
    POSTFX.quad.material = mat;
    renderer.setRenderTarget(null);
  }

  function renderFrame() {
    if (!renderer || !sceneObj) return;
    if (!POSTFX.enabled || !POSTFX.ready) {
      renderer.render(sceneObj, camera);
      return;
    }
    const t0 = performance.now();
    // 场景 → rtS
    renderer.setRenderTarget(POSTFX.rtS);
    renderer.render(sceneObj, camera);
    // 亮通
    POSTFX.scBright.uniforms.tDiffuse.value = POSTFX.rtS.texture;
    _fsQuad(POSTFX.scBright);
    renderer.setRenderTarget(POSTFX.rtA);
    renderer.render(POSTFX.sceneQuad, POSTFX.camQuad);
    // 高斯 H/V（两遍 1/4 分辨率）
    POSTFX.scBlur.uniforms.tDiffuse.value = POSTFX.rtA.texture;
    POSTFX.scBlur.uniforms.uDir.value.set(1, 0);
    _fsQuad(POSTFX.scBlur);
    renderer.setRenderTarget(POSTFX.rtB);
    renderer.render(POSTFX.sceneQuad, POSTFX.camQuad);
    POSTFX.scBlur.uniforms.tDiffuse.value = POSTFX.rtB.texture;
    POSTFX.scBlur.uniforms.uDir.value.set(0, 1);
    _fsQuad(POSTFX.scBlur);
    renderer.setRenderTarget(POSTFX.rtA);
    renderer.render(POSTFX.sceneQuad, POSTFX.camQuad);
    // 合成（泛光叠加 + 暗角 + 饱和微调）
    POSTFX.scComp.uniforms.tScene.value = POSTFX.rtS.texture;
    POSTFX.scComp.uniforms.tBloom.value = POSTFX.rtA.texture;
    _fsQuad(POSTFX.scComp);
    renderer.setRenderTarget(null);
    renderer.render(POSTFX.sceneQuad, POSTFX.camQuad);
    // 性能看门狗：连续超阈值自动关（保留直渲底线）
    POSTFX.costMs = performance.now() - t0;
    POSTFX._avg = POSTFX._avg * 0.95 + POSTFX.costMs * 0.05;
    if (++POSTFX._frames > 90 && POSTFX._avg > 22) {
      POSTFX.enabled = false;
      if (window.DAYAN_EVENT) DAYAN_EVENT('warn', '泛光已自动关闭',
        '本机 GPU 负载过高（' + POSTFX._avg.toFixed(1) + 'ms/帧），已降级直渲保帧率');
    }
  }

  const POST_VERT = [
    'varying vec2 vUv;',
    'void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }'].join('\n');
  const POST_BRIGHT = [
    'varying vec2 vUv; uniform sampler2D tDiffuse; uniform float uThresh;',
    'void main(){',
    '  vec3 c = texture2D(tDiffuse, vUv).rgb;',
    '  float l = dot(c, vec3(0.299, 0.587, 0.114));',
    '  float w = smoothstep(uThresh, uThresh + 0.35, l);',
    '  gl_FragColor = vec4(c * w * w, 1.0);',
    '}'].join('\n');
  const POST_BLUR = [
    'varying vec2 vUv; uniform sampler2D tDiffuse; uniform vec2 uDir; uniform vec2 uTexel;',
    'void main(){',
    '  vec2 o = uDir * uTexel;',
    '  vec3 s = texture2D(tDiffuse, vUv).rgb * 0.227;',
    '  s += (texture2D(tDiffuse, vUv + o * 1.384).rgb + texture2D(tDiffuse, vUv - o * 1.384).rgb) * 0.316;',
    '  s += (texture2D(tDiffuse, vUv + o * 3.230).rgb + texture2D(tDiffuse, vUv - o * 3.230).rgb) * 0.070;',
    '  gl_FragColor = vec4(s, 1.0);',
    '}'].join('\n');
  const POST_COMP = [
    'varying vec2 vUv; uniform sampler2D tScene; uniform sampler2D tBloom;',
    'uniform float uBloom; uniform float uVig; uniform float uSat;',
    'void main(){',
    '  vec3 c = texture2D(tScene, vUv).rgb;',
    '  c += texture2D(tBloom, vUv).rgb * uBloom;',
    '  float l = dot(c, vec3(0.299, 0.587, 0.114));',
    '  c = mix(vec3(l), c, uSat);',
    '  vec2 d = vUv - 0.5;',
    '  c *= 1.0 - uVig * smoothstep(0.18, 0.78, dot(d, d) * 2.4);',
    '  gl_FragColor = vec4(c, 1.0);',
    '}'].join('\n');

  // ---------- B. 昼夜循环 ----------
  const DAYCYCLE = {
    h: 9.2, ensureDone: false, lamps: [], lights: [],
    ensure() {
      if (this.ensureDone || !sceneObj) return;
      this.ensureDone = true;
      if (!window._vizLights || !window._vizLights.key) {
        const key = new THREE.DirectionalLight(0xfff2e0, 1.2);
        key.position.set(24, 40, 14);
        sceneObj.add(key);
        const hemi = new THREE.HemisphereLight(0x9ab8e0, 0x4a4a44, 0.7);
        sceneObj.add(hemi);
        window._vizLights = Object.assign(window._vizLights || {},
          { key, hemi });
      }
      if (!sceneObj.fog) {
        sceneObj.fog = new THREE.Fog(0x8ab4dc, 70, 340);
      }
    },
  };

  function dayCycleTick(dt) {
    if (!window._vizDayCycle || !sceneObj || currentScene?.type?.startsWith('state_')) return;
    DAYCYCLE.ensure();
    DAYCYCLE.h = (DAYCYCLE.h + dt * (24 / 160)) % 24;   // 160 秒一昼夜
    applyDayPhase(DAYCYCLE.h);
  }

  function _lerpC(a, b, w) { return a.clone().lerp(b, Math.max(0, Math.min(1, w))); }
  function _mix3(ca, cb, cc, wDay, wDusk) {
    // night=cc, dusk=cb, day=ca：先夜→暮（wDusk），再暮→昼（wDay）
    const base = _lerpC(cc, cb, wDusk);
    return _lerpC(base, ca, wDay);
  }

  function applyDayPhase(h) {
    // 权重：分段把 24h 映射到 day/dusk/night 三锚
    let wDay = 0, wDusk = 0;
    if (h >= 7 && h < 17) { wDay = 1; }
    else if (h >= 5 && h < 7) { wDusk = 1 - (h - 5) / 2; wDay = (h - 5) / 2; }
    else if (h >= 17 && h < 20) { wDay = 1 - (h - 17) / 3; wDusk = (h - 17) / 3; }
    const dark = Math.max(0, Math.min(1, 1 - wDay - wDusk * 0.55));
    window._vizDarkness = dark;

    const day = MOODS.day, dusk = MOODS.dusk, night = MOODS.night;
    const _c = (x) => new THREE.Color(x);
    // 天穹三段渐变
    const dome = sceneObj.children.find(c => c.geometry && c.geometry.type === 'SphereGeometry' && c.material && c.material.map);
    if (dome && dome.material.map) {
      const stops = [0, 0.58, 1].map((_, i) => {
        const cn = _c(night.dome[i]), cd = _c(dusk.dome[i]), cl = _c(day.dome[i]);
        return _mix3(cl, cd, cn, wDay, wDusk).getStyle();
      });
      const c2 = document.createElement('canvas');
      c2.width = 4; c2.height = 256;
      const g2 = c2.getContext('2d');
      const gr2 = g2.createLinearGradient(0, 0, 0, 256);
      gr2.addColorStop(0, stops[0]); gr2.addColorStop(0.58, stops[1]); gr2.addColorStop(1, stops[2]);
      g2.fillStyle = gr2; g2.fillRect(0, 0, 4, 256);
      dome.material.map.image = c2;
      dome.material.map.needsUpdate = true;
    }
    sceneObj.background = _mix3(_c(day.bg), _c(dusk.bg), _c(night.bg), wDay, wDusk);
    sceneObj.fog.color = _mix3(_c(day.fog[0]), _c(dusk.fog[0]), _c(night.fog[0]), wDay, wDusk);
    sceneObj.fog.near = night.fog[1] + (day.fog[1] - night.fog[1]) * wDay;
    sceneObj.fog.far = night.fog[2] + (day.fog[2] - night.fog[2]) * wDay;
    const L = window._vizLights || {};
    if (L.key) {
      L.key.intensity = night.key[1] + (day.key[1] - night.key[1]) * wDay;
      L.key.color = _mix3(_c(day.key[0]), _c(dusk.key[0]), _c(night.key[0]), wDay, wDusk);
      // 太阳随时间绕场：黄昏/清晨角度低、色暖
      const ang = ((h - 6) / 12) * Math.PI;   // 6h→0, 18h→π
      L.key.position.set(Math.cos(ang) * 46, Math.max(6, Math.sin(ang) * 44), 18);
    }
    if (L.hemi) {
      L.hemi.intensity = night.hemi[2] + (day.hemi[2] - night.hemi[2]) * wDay;
      L.hemi.color = _mix3(_c(day.hemi[0]), _c(dusk.hemi[0]), _c(night.hemi[0]), wDay, wDusk);
    }
    if (renderer) renderer.toneMappingExposure =
      night.exposure + (day.exposure - night.exposure) * wDay;
    // 灯火随黑暗渐亮
    DAYCYCLE.lamps.forEach(sp => { sp.material.opacity = 0.18 + dark * 0.8; });
    DAYCYCLE.lights.forEach(lt => { lt.intensity = dark * lt.userData.maxI; });
  }

  function ensureNightLights(scene) {
    if (DAYCYCLE.lights.length) return;
    // 预算内真点光：环道 4 角 + 场心，夜晚点亮
    const spots = [[-30, 0, -30], [30, 0, -30], [-30, 0, 30], [30, 0, 30], [0, 0, 0]];
    spots.forEach(([x, , z]) => {
      const pl = new THREE.PointLight(0xffd98c, 0, 42, 1.8);
      pl.position.set(x, 7, z);
      pl.userData.maxI = 1.15;
      scene.add(pl);
      DAYCYCLE.lights.push(pl);
      const sp = new THREE.Sprite(new THREE.SpriteMaterial({
        map: makeGlowTexture('#ffd98c'), color: 0xffd98c,
        transparent: true, opacity: 0.2, depthWrite: false,
        blending: THREE.AdditiveBlending }));
      sp.scale.set(7, 7, 1); sp.position.set(x, 7, z);
      scene.add(sp);
      DAYCYCLE.lamps.push(sp);
    });
  }

  // ---------- C. 数据驱动特效 ----------
  const FXREG = { halos: [], trails: [], waves: [] };

  function _fxHalo(colorHex) {
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({
      map: makeGlowTexture('#ff6a8a'), color: colorHex,
      transparent: true, opacity: 0.0, depthWrite: false,
      blending: THREE.AdditiveBlending }));
    sp.scale.set(2.6, 2.6, 1);
    sp.userData.isFxHalo = true;
    return sp;
  }

  function updateEntityFX(group, fr) {
    const dark = window._vizDarkness || 0;
    let haloN = 0, trailN = 0;
    displayEntities(fr).forEach(ent => {
      const m = stateEntityMesh(ent.id);
      if (!m) return;
      // --- 车灯（夜）+ 刹车闪红 ---
      if (ent.type === 'car' && !m.userData.instancedCar) {
        if (!m.userData.lightsFx) {
          const head = new THREE.Group();
          [-0.34, 0.34].forEach(off => {
            const sp = new THREE.Sprite(new THREE.SpriteMaterial({
              map: makeGlowTexture('#fff3d0'), color: 0xfff3d0,
              transparent: true, opacity: 0.95, depthWrite: false,
              blending: THREE.AdditiveBlending }));
            sp.scale.set(1.5, 1.1, 1); sp.position.set(1.05, 0.05, off);
            head.add(sp);
          });
          const tail = new THREE.Group();
          [-0.34, 0.34].forEach(off => {
            const sp = new THREE.Sprite(new THREE.SpriteMaterial({
              map: makeGlowTexture('#ff4d5f'), color: 0xff4d5f,
              transparent: true, opacity: 0.85, depthWrite: false,
              blending: THREE.AdditiveBlending }));
            sp.scale.set(0.85, 0.6, 1); sp.position.set(-1.05, 0.05, off);
            sp.userData.isTail = true;
            tail.add(sp);
          });
          m.add(head); m.add(tail);
          m.userData.lightsFx = { head, tail };
        }
        const on = dark > 0.45 && m.visible;
        m.userData.lightsFx.head.visible = on;
        m.userData.lightsFx.tail.visible = on;
        if (on) {
          const prev = m.userData.prevSpeed;
          const braking = typeof prev === 'number' &&
            typeof ent.speed === 'number' && (prev - ent.speed) > 0.55;
          m.userData.lightsFx.tail.children.forEach(sp => {
            sp.material.opacity = braking ? 1.0 : 0.55;
            sp.scale.set(braking ? 1.5 : 0.85, braking ? 1.0 : 0.6, 1);
          });
        }
        m.userData.prevSpeed = ent.speed;
      }
      // --- 感染脉冲光环：状态 I*/infected，或携带 I>0 的个体 ---
      const infected = ent.state === 'infected' || ent.state === 'I' ||
        (typeof ent.infected === 'number' && ent.infected > 0.5) ||
        (ent.state && /^I[_=]/.test(String(ent.state)));
      if (infected && haloN < 120 && studioProfile?.kind !== 'cohorts') {
        if (!m.userData.halo) {
          m.userData.halo = _fxHalo(0xff5d80);
          m.add(m.userData.halo);
          FXREG.halos.push(m.userData.halo);
        }
        m.userData.halo.visible = true;
        m.userData.halo.position.set(0, 1.5, 0);
        haloN++;
      } else if (m.userData.halo) {
        m.userData.halo.visible = false;
      }
      // --- 疏散拖尾：运动中的行人，位置环形缓冲 ---
      if (ent.type === 'pedestrian' && ent.state === 'moving' &&
          m.visible && trailN < 30) {
        if (!m.userData.trailLine) {
          const g = new THREE.BufferGeometry();
          g.setAttribute('position', new THREE.Float32BufferAttribute(
            new Float32Array(18), 3));
          const line = new THREE.Line(g, new THREE.LineBasicMaterial({
            color: 0x9fe8ff, transparent: true, opacity: 0.4,
            depthWrite: false }));
          line.userData.isFxTrail = true;
          line.frustumCulled = false;
          group.add(line);
          m.userData.trailLine = line;
          m.userData.trailPts = [];
          FXREG.trails.push(line);
        }
        const pts = m.userData.trailPts;
        pts.push(m.position.x, m.position.y, m.position.z);
        while (pts.length > 18) { pts.shift(); pts.shift(); pts.shift(); }
        const arr = m.userData.trailLine.geometry.attributes.position.array;
        const seg = pts.length / 3;
        for (let i = 0; i < 6; i++) {
          const j = seg - 6 + i;   // 最近 6 个保存位置；不足用当前位置补齐
          arr[i * 3] = j >= 0 ? pts[j * 3] : m.position.x;
          arr[i * 3 + 1] = j >= 0 ? pts[j * 3 + 1] : m.position.y;
          arr[i * 3 + 2] = j >= 0 ? pts[j * 3 + 2] : m.position.z;
        }
        m.userData.trailLine.geometry.attributes.position.needsUpdate = true;
        m.userData.trailLine.visible = true;
        trailN++;
      } else if (m.userData.trailLine) {
        m.userData.trailLine.visible = false;
      }
    });
  }

  function spawnEventWaves(st, prevFr, fr) {
    if (!sceneLayers.events||!st.events || !st.events.length || reduced.matches) return;
    const t0 = prevFr ? (prevFr.sim_t ?? -1e9) : -1e9;
    const t1 = fr.sim_t ?? 1e9;
    st.events.forEach(ev => {
      if(ev.applied===false)return;
      const et = ev.sim_t ?? ev.t;
      if (typeof et !== 'number' || et <= t0 || et > t1) return;
      const coords=eventPosition(ev,fr);
      if(!coords)return;
      if (FXREG.waves.length >= 2) return;
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(0.8, 1.15, 48),
        new THREE.MeshBasicMaterial({ color: 0xffc85a, transparent: true,
          opacity: 0.75, side: THREE.DoubleSide, depthWrite: false }));
      ring.rotation.x = -Math.PI / 2;
      const [x,,z]=stateWorldXY(coords,fr);
      ring.position.set(x,.28,z);
      ring.userData.isFxWave = { born: performance.now() };
      ring.userData.sceneLayer='events';
      getScene().add(ring);
      FXREG.waves.push(ring);
    });
  }

  function fxTick(dt, t) {
    // 感染光环呼吸
    const now = performance.now();
    FXREG.halos.forEach(sp => {
      if (!sp.visible) return;
      const k = 0.55 + 0.45 * Math.sin(now * 0.004 + sp.id);
      sp.material.opacity = 0.32 + 0.4 * k;
      const sc = 2.3 + 0.9 * k;
      sp.scale.set(sc, sc, 1);
    });
    // 冲击波扩散
    for (let i = FXREG.waves.length - 1; i >= 0; i--) {
      const ring = FXREG.waves[i];
      const age = (now - ring.userData.isFxWave.born) / 900;
      if (age >= 1) {
        getScene().remove(ring);
        ring.geometry.dispose(); ring.material.dispose();
        FXREG.waves.splice(i, 1);
        continue;
      }
      const r = 0.8 + age * 24;
      ring.scale.set(r, r, 1);
      ring.material.opacity = 0.75 * (1 - age);
    }
  }

  // ---------- D. 开场推近镜头 ----------
  const INTRO = { active: false, t0: 0, dur: 620, from: null, to: null };
  function startIntroCinematic() {
    if (!camera || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    INTRO.to = camera.position.clone();
    INTRO.from = INTRO.to.clone().lerp(overviewTarget,-.16);
    INTRO.t0 = performance.now();
    INTRO.active = true;
  }
  function introTick() {
    if (!INTRO.active || !camera) return;
    const a = Math.min(1, (performance.now() - INTRO.t0) / INTRO.dur);
    const e = 1 - Math.pow(1 - a, 3);   // easeOutCubic
    camera.position.lerpVectors(INTRO.from, INTRO.to, e);
    camera.lookAt(overviewTarget);
    if (a >= 1) INTRO.active = false;
  }
  window.addEventListener('pointerdown', () => { INTRO.active = false; }, { once: false });

  window._vizDayCycle = true;


  // ---- 导出到全局 ----
  window.DAYAN3D = {
    init,
    switchScene,
    autoDetect,
    visualize,
    visualize2: visualize,
    visualizeState,
    completeArchive,
    preview,
    clear:clearSavedWorld,
    renderAt(t){window._vizNow=t;window._vizStateIdx=-1;if(window._vizStateStream)vizStateUpdate(t);else if(currentScene?.update)currentScene.update(t,0);if(renderer&&sceneObj)renderer.render(sceneObj,camera);},
    selectEntity:selectStateEntity,
    focusEntity:focusStateEntity,
    focusEvent,
    resetCamera:resetStateCamera,
    setCameraPreset(name){
      if(!['fit','plan','low'].includes(name)||!viewHull.length)return false;
      if(followingStateEntity)followStateEntity('',false);
      cameraPreset=name;stateCameraOverview=true;reportPose();fitStateCamera(true);return true;
    },
    setSceneLayer,
    get diagnostics(){
      if(!renderer)return null;
      const {render,memory}=renderer.info;
      const group=getScene().children.find(c=>c.userData?.isStateGroup);
      let visibleEntities=0;
      for(const mesh of group?.userData.meshMap?.values()||[])if(mesh.userData.entityId!==undefined&&mesh.visible)visibleEntities++;
      return {drawCalls:render.calls,triangles:render.triangles,geometries:memory.geometries,textures:memory.textures,visibleEntities,
        spatial:studioStage?.userData.spatialFacts||null,
        referenceGroundSuppressed:studioStage?.userData.ground?(!studioStage.userData.ground.deck.visible&&!studioStage.userData.ground.seams.visible):null};
    },
    followEntity:followStateEntity,
    entityPose(id){const mesh=stateEntityMesh(id);return mesh?{position:mesh.position.toArray(),rotation:mesh.rotation.toArray(),pose:mesh.userData.pose,visible:mesh.visible}:null;},
    get cameraState(){return {position:camera?.position.toArray(),quaternion:camera?.quaternion.toArray(),aspect:camera?.aspect,fov:camera?.fov,following:followingStateEntity||null};},
    get presentation(){return studioProfile?{...studioProfile,smoothing:stateSmoothing}:null;},
    setSmoothing(enabled){stateSmoothing=!!enabled;const check=document.getElementById('sceneSmoothing');if(check)check.checked=stateSmoothing;window._vizStateIdx=-1;this.renderAt(window.DAYAN_RESULTS?.time||0);},
    setMood,
    setLayer,
    setGroupFilter,
    pause,
    resume,
    setPostFX(on){POSTFX.userOn=!!on;if(POSTFX.ready){POSTFX.enabled=POSTFX.userOn;}},
    get postFX(){return {enabled:POSTFX.enabled,ready:POSTFX.ready,costMs:POSTFX.costMs};},
    setDayCycle(on){window._vizDayCycle=!!on;if(on)DAYCYCLE.ensure();},
    setDayPhase(h){DAYCYCLE.h=((Number(h)||0)%24+24)%24;},
    get dayPhase(){return DAYCYCLE.h;},
    get currentType() { return currentScene ? currentScene.type : null; }
  };

  // 自动初始化
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      init('viz3dContainer');
      getScene().background=new THREE.Color(0x101f2e);
    });
  } else {
    init('viz3dContainer');
    getScene().background=new THREE.Color(0x101f2e);
  }
})();
