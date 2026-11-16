import io

p = 'viz3d.js'
s = io.open(p, encoding='utf-8').read()

# ===== 1. 情绪配置表 + setMood（在 addSkyDome 前插入）=====
anchor = '  let blinkers = [];   // 天线红色闪灯（clearScene 复位，frame 循环驱动）'
assert anchor in s
mood_sys = anchor + '''

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

  function setMood(moodName, density) {
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
  function densitySkipRate() { return 0.1 + (1 - window._vizDensity) * 0.45; }'''
s = s.replace(anchor, mood_sys)

# ===== 2. clearScene 清天气组引用 =====
s = s.replace("""    window._vizAgentPos = null;
    blinkers = [];
    clouds = [];""",
"""    window._vizAgentPos = null;
    blinkers = [];
    clouds = [];
    if (weatherGroup) { weatherGroup = null; }   // 场景重建后由 visualize/setMood 重挂""")

# ===== 3. frame 循环驱动天气 =====
s = s.replace("""    clouds.forEach(cl => {
      cl.sp.position.x += cl.v * 0.016;
      if (cl.sp.position.x > 95) cl.sp.position.x = -95;
    });""",
"""    clouds.forEach(cl => {
      cl.sp.position.x += cl.v * 0.016;
      if (cl.sp.position.x > 95) cl.sp.position.x = -95;
    });
    updateWeather(dt);""")

# ===== 4. addLights：存引用供 setMood 调强度 =====
s = s.replace("""    const key = new THREE.DirectionalLight(0xfff2e0, 1.7);
    key.position.set(18, 32, 10);""",
"""    const key = new THREE.DirectionalLight(0xfff2e0, 1.7);
    key.position.set(18, 32, 10);
    window._vizLights = window._vizLights || {};
    window._vizLights.key = key;""")
s = s.replace("""    const hemi = new THREE.HemisphereLight(0x9ab8e0, 0x5a5a50, 0.75);
    scene.add(hemi);""",
"""    const hemi = new THREE.HemisphereLight(0x9ab8e0, 0x5a5a50, 0.75);
    scene.add(hemi);
    if (window._vizLights) window._vizLights.hemi = hemi;""")
s = s.replace("""    scene.add(new THREE.AmbientLight(0xb8c4d8, 0.5));""",
"""    const amb = new THREE.AmbientLight(0xb8c4d8, 0.5);
    scene.add(amb);
    if (window._vizLights) window._vizLights.amb = amb;""")

# ===== 5. addSkyDome 尊重当前 mood（重建场景时穹顶跟随）=====
s = s.replace("function addSkyDome(scene, top = '#2a5aa8', mid = '#6a9ad8', bottom = '#aac8e8') {",
              "function addSkyDome(scene, top, mid, bottom) {\n    const MC = (MOODS[window._vizMood] || MOODS.day).dome;\n    top = top || MC[0]; mid = mid || MC[1]; bottom = bottom || MC[2];")

# ===== 6. addGround 默认色尊重雨/雪 mood（湿地面/雪地）=====
s = s.replace("function addGround(scene, size = 40, color = 0x5a6470) {",
              "function addGround(scene, size = 40, color) {\n    if (!color) color = window._vizMood === 'snow' ? 0xd8e2ea : window._vizMood === 'night' ? 0x2a3644 : 0x5a6470;")

# ===== 7. makeBuildings：主题调色板 + 密度跳过率 + 材质明度跟 mood =====
s = s.replace("const paletteArr = palette || [0xd96c4f, 0x3aa6a0, 0xe0b45c, 0xe87a8a, 0x5a8ad0, 0x9a6ac0, 0xd8cfc0, 0xc9beb0];",
              "const paletteArr = palette || themePalette();")
s = s.replace("      if (Math.random() < 0.1) continue;", "")  # city 内已有同款——改下面这处 makeBuildings 无 skip，跳过
io.open(p, 'w', encoding='utf-8').write(s)
print('mood system part1 done', len(s))
