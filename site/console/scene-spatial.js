/* Actual height fields, floor slabs and connector polylines from saved frames. */
(function () {
  'use strict';
  function world(point,frame){
    const [x0,y0,x1,y1]=frame.space.bounds,s=DAYAN_SCENE_STUDIO.scaleFor(frame);
    return [(point[0]-(x0+x1)/2)*s,point[2]*s,((y0+y1)/2-point[1])*s];
  }
  function dispose(group){group.traverse(o=>{o.geometry?.dispose();if(o.material){for(const m of Array.isArray(o.material)?o.material:[o.material]){m.map?.dispose();m.dispose();}}});}
  function surface(group,positions,indices,color,source,opacity=1){
    const geometry=new THREE.BufferGeometry();
    geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setIndex(indices);geometry.computeVertexNormals();
    const mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color,side:THREE.DoubleSide,roughness:.88,transparent:opacity<1,opacity,depthWrite:opacity===1}));
    mesh.receiveShadow=true;mesh.userData.spatialSource=source;group.add(mesh);return mesh;
  }
  function label(group,text,position){
    const canvas=document.createElement('canvas');canvas.width=512;canvas.height=96;
    const context=canvas.getContext('2d');context.font='30px "Microsoft YaHei", sans-serif';context.fillStyle='#dce9ee';context.textAlign='center';context.fillText(text,256,60,500);
    const texture=new THREE.CanvasTexture(canvas),sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:texture,transparent:true,depthTest:false}));
    sprite.scale.set(13,2.4,1);sprite.position.fromArray(position);sprite.position.y+=1.3;sprite.userData.sceneLayer='labels';group.add(sprite);
  }
  function update(stage,frame,applyLayer){
    const space=frame.space||{},active=!!(space.terrain||space.floors?.length||space.connectors?.length);
    if(stage.userData.ground){
      for(const part of [stage.userData.ground.deck,stage.userData.ground.seams]){
        part.userData.spatialSuppressed=active;
        if(active)part.visible=false;else applyLayer?.(part);
      }
    }
    if(!active){
      if(stage.userData.spatial){stage.remove(stage.userData.spatial);dispose(stage.userData.spatial);delete stage.userData.spatial;delete stage.userData.spatialKey;delete stage.userData.spatialFacts;}
      return;
    }
    const key=JSON.stringify(space);if(stage.userData.spatialKey===key)return;
    if(stage.userData.spatial){stage.remove(stage.userData.spatial);dispose(stage.userData.spatial);}
    const group=new THREE.Group();group.userData.sceneLayer='base';stage.add(group);
    stage.userData.spatial=group;stage.userData.spatialKey=key;
    const stats={terrainVertices:0,floors:[],connectors:[],unit:space.unit,verticalBounds:space.vertical_bounds};
    if(stage.userData.ground){stage.userData.ground.deck.visible=false;stage.userData.ground.seams.visible=false;}
    if(space.terrain){
      const t=space.terrain,h=t.heights,positions=[],indices=[];
      for(let j=0;j<h.length;j++)for(let i=0;i<h[0].length;i++)positions.push(...world([t.origin[0]+i*t.spacing[0],t.origin[1]+j*t.spacing[1],h[j][i]],frame));
      for(let j=0;j<h.length-1;j++)for(let i=0;i<h[0].length-1;i++){const a=j*h[0].length+i,b=a+1,c=a+h[0].length,d=c+1;indices.push(a,c,b,b,c,d);}
      const land=surface(group,positions,indices,0x587c69,{kind:'terrain',id:t.id,heights:t.heights});
      const lines=new THREE.LineSegments(new THREE.WireframeGeometry(land.geometry),new THREE.LineBasicMaterial({color:0x93c1a8,transparent:true,opacity:.16}));group.add(lines);
      stats.terrainVertices=positions.length/3;
      label(group,t.label||t.id,world([t.origin[0],t.origin[1],h[0][0]],frame));
    }
    (space.floors||[]).forEach((floor,i)=>{
      function shape(bounds,Shape){const [x0,y0,x1,y1]=bounds,points=[[x0,y0],[x1,y0],[x1,y1],[x0,y1]].map(p=>world([...p,0],frame));const s=new Shape();s.moveTo(points[0][0],-points[0][2]);for(const p of points.slice(1))s.lineTo(p[0],-p[2]);s.closePath();return s;}
      const outline=shape(floor.bounds,THREE.Shape);
      (floor.holes||[]).forEach(bounds=>outline.holes.push(shape(bounds,THREE.Path)));
      const geo=new THREE.ShapeGeometry(outline);geo.rotateX(-Math.PI/2);
      const deck=new THREE.Mesh(geo,new THREE.MeshStandardMaterial({color:[0x708a9a,0x8d99b2,0x759c98][i%3],side:THREE.DoubleSide,roughness:.8,transparent:true,opacity:.52,depthWrite:false}));
      deck.position.y=floor.elevation*DAYAN_SCENE_STUDIO.scaleFor(frame);deck.userData.spatialSource={kind:'floor',...floor};deck.receiveShadow=true;group.add(deck);
      const edges=new THREE.LineSegments(new THREE.EdgesGeometry(geo),new THREE.LineBasicMaterial({color:0xb7d8e5,transparent:true,opacity:.7}));edges.position.y=deck.position.y+.02;group.add(edges);
      const [x0,y0,x1,y1]=floor.bounds;label(group,(floor.label||floor.id)+' · '+floor.elevation+' '+space.unit,world([(x0+x1)/2,y1,floor.elevation],frame));
      stats.floors.push({id:floor.id,elevation:floor.elevation,worldY:deck.position.y});
    });
    (space.connectors||[]).forEach(connection=>{
      const positions=[],indices=[],s=DAYAN_SCENE_STUDIO.scaleFor(frame);
      connection.polyline.slice(0,-1).forEach((point,i)=>{
        const a=world(point,frame),b=world(connection.polyline[i+1],frame),dx=b[0]-a[0],dz=b[2]-a[2],length=Math.hypot(dx,dz),w=connection.width*s/2;
        const nx=length?dz/length:1,nz=length?-dx/length:0,start=positions.length/3;
        for(const p of [a,b])for(const sign of [-1,1])positions.push(p[0]+sign*nx*w,p[1]+.015,p[2]+sign*nz*w);
        indices.push(start,start+2,start+1,start+1,start+2,start+3);
      });
      const mesh=surface(group,positions,indices,0xc4ad7f,{kind:'connector',...connection});
      const edge=new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry),new THREE.LineBasicMaterial({color:0xf2d59d}));group.add(edge);
      label(group,connection.label||connection.id,world(connection.polyline[Math.floor(connection.polyline.length/2)],frame));
      stats.connectors.push({id:connection.id,worldPoints:connection.polyline.map(p=>world(p,frame)),kind:connection.kind});
    });
    stage.userData.spatialFacts=stats;
  }
  window.DAYAN_SPATIAL={update,world};
})();
