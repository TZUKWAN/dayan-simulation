import io

p = 'viz3d.js'
s = io.open(p, encoding='utf-8').read()

# 1) setMood 导出
s = s.replace("""  window.DAYAN3D = {
    init,
    switchScene,
    autoDetect,
    visualize,
    setLayer,
    setGroupFilter,
    pause,
    resume,
    get currentType() { return currentScene ? currentScene.type : null; }
  };""",
"""  window.DAYAN3D = {
    init,
    switchScene,
    autoDetect,
    visualize,
    visualize2: visualize,
    setMood,
    setLayer,
    setGroupFilter,
    pause,
    resume,
    get currentType() { return currentScene ? currentScene.type : null; }
  };""")

# 2) 城市街区跳过率跟密度
s = s.replace("""      for (const ox of [-2.5, 2.5]) for (const oz of [-2.5, 2.5]) {
        if (Math.random() < 0.1) continue;""",
"""      for (const ox of [-2.5, 2.5]) for (const oz of [-2.5, 2.5]) {
        if (Math.random() < densitySkipRate()) continue;""")

# 3) city 楼色数组改主题调色板
s = s.replace("const col = [0xd96c4f, 0x3aa6a0, 0xe0b45c, 0xe87a8a, 0x5a8ad0, 0x9a6ac0, 0xc8b8a8][Math.floor(Math.random() * 7)];",
              "const col = themePalette()[Math.floor(Math.random() * 8)];")

# 4) epidemic 人群规模跟密度
s = s.replace("    const AG = 220;\n    const crowd = makeCrowd(AG, 0x00e5ff);",
              "    const AG = Math.round(120 + 140 * (window._vizDensity || 0.7));\n    const crowd = makeCrowd(AG, 0x00e5ff);")

# 5) panic 人群规模跟密度
s = s.replace("    const AG = 200;\n    const crowd = makeCrowd(AG, 0x47e3d1);\n    scene.add(crowd);\n    const agents = [];\n    for (let i = 0; i < AG; i++) {\n      const r = 3 + Math.sqrt(Math.random()) * 11, th = Math.random() * Math.PI * 2;",
              "    const AG = Math.round(110 + 130 * (window._vizDensity || 0.7));\n    const crowd = makeCrowd(AG, 0x47e3d1);\n    scene.add(crowd);\n    const agents = [];\n    for (let i = 0; i < AG; i++) {\n      const r = 3 + Math.sqrt(Math.random()) * 11, th = Math.random() * Math.PI * 2;")

io.open(p, 'w', encoding='utf-8').write(s)
print('mood part2 viz done')
