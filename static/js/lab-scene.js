import * as T from '../vendor/three/three.module.js';
import {mergeGeometries} from '../vendor/three/BufferGeometryUtils.js';

// 한 방·8명 공유 리그. 외부 모델/텍스처 요청 없이 실제 메시를 생성해요.
export function createLabScene({canvas, labels, roster, onSelect, reducedMotion, onFailure}) {
  const lowDetail = innerWidth < 760;
  const renderer = new T.WebGLRenderer({canvas, antialias: true, alpha: false, powerPreference: 'low-power'});
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, innerWidth < 760 ? 1.25 : 1.5));
  renderer.setClearColor(0xf4f5f8);
  renderer.outputColorSpace = T.SRGBColorSpace;
  renderer.toneMapping = T.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = !lowDetail;
  renderer.shadowMap.type = T.PCFShadowMap;
  renderer.shadowMap.autoUpdate = false;
  renderer.shadowMap.needsUpdate = true;
  const world = new T.Scene();
  const architecture = new T.Group(); world.add(architecture);
  const camera = new T.OrthographicCamera(-9,9,7,-7,.1,100);
  const geos = new Map(), mats = new Map(), textures = new Set();
  const actors = new Map(), hits = [], projected = new T.Vector3();
  let selected = '', active = '', meeting = '', paused = reducedMotion, shown = true, disposed = false;
  let frame = 0, previousFrame = 0, animationTime = 0, needRender = true;
  const baseYaw = .68, baseTilt = .77;
  let yaw = baseYaw, tilt = baseTilt, size = 20.0;
  let targetYaw = yaw, targetTilt = tilt, targetSize = size;
  const look = new T.Vector3(0,1.15,0), lookTarget = look.clone();
  const material = (color, extra = {}) => {
    const key = `${color}:${JSON.stringify(extra)}`;
    if (!mats.has(key)) mats.set(key, new T.MeshStandardMaterial({color, roughness: .75, ...extra}));
    return mats.get(key);
  };
  const white = material('#ffffff'), wall = material('#e7e9f0'), pale = material('#f4f5f8');
  const indigo = material('#4f46e5'), ink = material('#292b36'), silver = material('#b9bdcc', {metalness:.35,roughness:.4});
  const wood = material('#c6b7a5'), paper = material('#fafafa'), fabric = material('#9b9fb4');
  const clay = material('#ffffff', {vertexColors:true});
  function batchGeometry(o,matrix) {
    let g=o.geometry.clone();g.applyMatrix4(matrix);
    if(g.index){const expanded=g.toNonIndexed();g.dispose();g=expanded;}
    const colored=!o.material.map&&!o.material.transparent&&!o.material.metalness;
    if(colored && !g.hasAttribute('color')) {
      const rgb=new Float32Array(g.attributes.position.count*3),c=o.material.color;
      for(let i=0;i<rgb.length;i+=3){rgb[i]=c.r;rgb[i+1]=c.g;rgb[i+2]=c.b;}
      g.setAttribute('color',new T.BufferAttribute(rgb,3));
    }
    return {geo:g,mat:colored?clay:o.material};
  }
  function geometry(key, create) { if (!geos.has(key)) geos.set(key, create()); return geos.get(key); }
  function group(parent = architecture, x = 0,y = 0,z = 0) { const a = new T.Group(); a.position.set(x,y,z); parent.add(a); return a; }
  function mesh(geo, mat, x,y,z, parent = architecture, scale) {
    const a = new T.Mesh(geo,mat); a.position.set(x,y,z); if (scale) a.scale.set(...scale);
    a.castShadow = true; a.receiveShadow = true; parent.add(a); return a;
  }
  function box(w,h,d,mat,x,y,z,parent = architecture, radius = .04) {
    const geo = geometry(`b:${w}:${h}:${d}:${radius}`, () => {
      if (!radius) return new T.BoxGeometry(w,h,d);
      const r = Math.min(radius,w/2-.001,h/2-.001,d/2-.001);
      const shape = new T.Shape();
      shape.moveTo(-w/2+r,-h/2); shape.lineTo(w/2-r,-h/2); shape.quadraticCurveTo(w/2,-h/2,w/2,-h/2+r);
      shape.lineTo(w/2,h/2-r); shape.quadraticCurveTo(w/2,h/2,w/2-r,h/2);
      shape.lineTo(-w/2+r,h/2); shape.quadraticCurveTo(-w/2,h/2,-w/2,h/2-r);
      shape.lineTo(-w/2,-h/2+r); shape.quadraticCurveTo(-w/2,-h/2,-w/2+r,-h/2);
      const g = new T.ExtrudeGeometry(shape,{depth:d-2*r,bevelEnabled:true,bevelSize:r,bevelThickness:r,bevelSegments:lowDetail?1:2,steps:1,curveSegments:lowDetail?2:3});
      g.translate(0,0,-d/2+r); return g;
    });
    return mesh(geo,mat,x,y,z,parent);
  }
  function sphere(r,mat,x,y,z,parent = architecture,scale) {
    return mesh(geometry(`s:${r}`,()=>new T.SphereGeometry(r,lowDetail?8:12,lowDetail?6:8)),mat,x,y,z,parent,scale);
  }
  function cylinder(rt,rb,h,mat,x,y,z,parent = architecture,segments = 10) {
    return mesh(geometry(`c:${rt}:${rb}:${h}:${segments}`,()=>new T.CylinderGeometry(rt,rb,h,segments)),mat,x,y,z,parent);
  }
  function limb(start,end,r,mat,parent) {
    const a = new T.Vector3(...start), b = new T.Vector3(...end), direction = b.clone().sub(a);
    const m = cylinder(r,r,direction.length(),mat,...a.clone().add(b).multiplyScalar(.5).toArray(),parent,8);
    m.quaternion.setFromUnitVectors(new T.Vector3(0,1,0),direction.normalize());
    sphere(r,mat,...start,parent); sphere(r,mat,...end,parent); return m;
  }
  function texture(draw,w = 1024,h = 512) {
    const c = document.createElement('canvas'); c.width=w; c.height=h; draw(c.getContext('2d'),w,h);
    const t = new T.CanvasTexture(c); t.colorSpace=T.SRGBColorSpace; textures.add(t); return t;
  }
  function art(map,w,h,x,y,z,parent = architecture) {
    const mat = new T.MeshBasicMaterial({map,transparent:true,depthWrite:false}); mats.set(map.uuid,mat);
    const p = mesh(geometry(`p:${w}:${h}`,()=>new T.PlaneGeometry(w,h)),mat,x,y,z,parent);
    p.castShadow=false; return p;
  }
  const contact = texture(ctx => {
    const g=ctx.createRadialGradient(128,128,8,128,128,126); g.addColorStop(0,'rgba(35,38,60,.24)'); g.addColorStop(.4,'rgba(35,38,60,.12)'); g.addColorStop(1,'rgba(35,38,60,0)'); ctx.fillStyle=g; ctx.fillRect(0,0,256,256);
  },256,256);
  function shadow(x,z,w,d,parent = architecture) { const a=art(contact,w,d,x,.012,z,parent); a.rotation.x=-Math.PI/2; }

  world.add(new T.HemisphereLight(0xffffff,0xc6c9db,1.8));
  const sun=new T.DirectionalLight(0xfffaf5,2.3); sun.position.set(-5,13,7); sun.castShadow=true;
  sun.shadow.mapSize.set(1024,1024); Object.assign(sun.shadow.camera,{left:-10,right:10,top:9,bottom:-9,near:.5,far:35});
  sun.shadow.normalBias=.035; sun.shadow.bias=-.0002; sun.shadow.radius=3; world.add(sun);
  const fill=new T.DirectionalLight(0xe8eaff,.9); fill.position.set(8,7,-3); world.add(fill);

  // 단면 모형의 기단과 앞쪽이 열린 두 면의 벽이에요.
  box(12.8,.35,9.7,white,0,-.25,0,architecture,.12);
  box(12.4,.13,9.3,material('#d7dae5'),0,-.03,0,architecture,.05);
  box(12.25,.08,9.15,pale,0,.07,0,architecture,.035);
  for (let x=-5;x<=5;x+=1) box(.013,.004,8.95,wall,x,.113,0,architecture,0);
  for (let z=-4;z<=4;z+=1) box(12,.004,.013,wall,0,.113,z,architecture,0);
  box(.18,3.45,9.25,white,-6.13,1.74,0,architecture,.025);
  box(12.35,3.45,.18,white,0,1.74,-4.58,architecture,.025);
  box(.06,.18,9.1,wall,-6.01,.23,0,architecture,.01);
  box(12.1,.18,.06,wall,0,.23,-4.45,architecture,.01);
  // 기단 테두리와 입구의 계단이에요.
  box(12.6,.045,.025,indigo,0,-.20,4.86,architecture,.005);
  box(2.5,.13,.55,wall,3.7,-.34,4.93,architecture,.04);
  box(2.8,.1,.55,white,3.7,-.45,5.18,architecture,.04);
  // 뒤쪽 벽의 연구실 간판이에요.
  art(texture((ctx,w,h)=>{
    ctx.fillStyle='#18181b';ctx.font='700 78px Pretendard, sans-serif';ctx.fillText('테크창 연구실',40,175);
    ctx.fillStyle='#71717a';ctx.font='28px Pretendard, sans-serif';ctx.fillText('생각을 연결하고, 근거로 확인해요.',42,235);
    ctx.fillStyle='#4f46e5';ctx.fillRect(45,72,70,8);
  }),4.9,2.45,-2.55,2.35,-4.47);
  // 창과 창틀은 반사색을 사용해 가볍게 표현해요.
  box(.035,2.35,3.75,material('#d6dbea',{roughness:.25,metalness:.2}),-6.015,2.05,1.1,architecture,.01);
  for (let z=-.75;z<3.1;z+=1.25) box(.08,2.4,.045,silver,-5.94,2.05,z,architecture,.005);
  box(.09,.045,3.8,silver,-5.94,2.25,1.1,architecture,.005);
  box(.3,.1,3.95,white,-5.88,.87,1.1);
  for(let i=0;i<5;i++) box(3.1,.012,.045,white,-4.2,.12+i*.003,-.1+i*.5,architecture,0).rotation.y=.2;

  function plant(x,z,scale=1) {
    const p=group(architecture,x,.1,z); p.scale.setScalar(scale);
    cylinder(.24,.18,.42,white,0,.21,0,p); cylinder(.22,.22,.02,wood,0,.43,0,p);
    for (let i=0;i<7;i++) {
      const angle=i*2.4, h=.6+(i%3)*.22;
      limb([0,.42,0],[Math.sin(angle)*.22,h,Math.cos(angle)*.22],.012,material('#777b72'),p);
      const leaf=sphere(.18,material(i%2?'#7d8978':'#abb5a5'),Math.sin(angle)*.27,h,Math.cos(angle)*.27,p,[.65,1.8,.35]); leaf.rotation.z=Math.sin(angle)*.7;
    }
    shadow(x,z,.85,.85);
  }
  plant(-5.3,3.6,1.25); plant(5.25,-3.5,1.2); plant(-5.3,-3.65,.8);
  // 뒤쪽 자료실의 책등은 중성색과 인디고를 사용해요.
  const shelf=group(architecture,-4.5,.1,-3.9);
  box(2.3,2.55,.45,wall,0,1.28,0,shelf);
  box(2.12,2.35,.08,pale,0,1.28,.25,shelf);
  for (let row=0;row<3;row++) {
    box(2.3,.07,.58,white,0,.25+row*.78,.1,shelf);
    let x=-1.02;
    for(let i=0;i<12;i++) {
      const w=.10+(i%3)*.02, h=.37+((i*7+row)%4)*.06;
      const m=[white,wall,fabric,indigo,wood][(i+row*2)%5];
      const book=box(w,h,.29,m,x+w/2,.3+row*.78+h/2,.32,shelf,.008);
      book.rotation.z=i===9?.13:0;
      box(w*.7,.018,.006,paper,x+w/2,.39+row*.78,.47,shelf,0); x+=w+.025;
    }
  }
  box(2.3,.08,.58,white,0,2.55,.1,shelf);
  // 보드가 자료에서 집필·검증으로 이어지는 흐름을 보여줘요.
  const board=group(architecture,3.25,2.25,-4.42);
  box(4.3,1.55,.06,wall,0,0,0,board);
  art(texture((ctx,w,h)=>{
    ctx.fillStyle='#fafafa';ctx.fillRect(0,0,w,h);
    ctx.fillStyle='#52525b';ctx.font='600 37px Pretendard, sans-serif';ctx.fillText('원문에서 시작해요',55,86);
    ['자료','집필','검증'].forEach((t,i)=>{ const x=55+i*320;ctx.fillStyle=i===2?'#4f46e5':'#e7e9f0';ctx.fillRect(x,146,245,110);ctx.fillStyle=i===2?'#fff':'#3f3f46';ctx.font='500 35px Pretendard, sans-serif';ctx.fillText(t,x+81,216);if(i<2){ctx.fillStyle='#a1a1aa';ctx.fillRect(x+261,199,38,3);} });
    for(let i=0;i<3;i++){ctx.fillStyle='#e4e4e7';ctx.fillRect(55,310+i*43,580-i*110,10);}
    ctx.strokeStyle='#4f46e5';ctx.lineWidth=6;ctx.beginPath();ctx.moveTo(735,419);ctx.lineTo(790,375);ctx.lineTo(846,390);ctx.lineTo(937,296);ctx.stroke();
  }),4.15,1.4,0,0,.04,board);

  const screenTexture=texture((ctx,w,h)=>{
    ctx.fillStyle='#33364b';ctx.fillRect(0,0,w,h);ctx.fillStyle='#9f9bea';ctx.fillRect(30,36,220,14);
    for(let i=0;i<8;i++){ctx.fillStyle=i%3===0?'#a5a2f3':'#777b92';ctx.fillRect(35+(i%2)*25,98+i*43,400-(i*61)%200,10);}
    ctx.fillStyle='#4f46e5';for(let i=0;i<5;i++)ctx.fillRect(615+i*63,350-(i*33)%175,36,90+(i*33)%175);
  });
  function monitor(x,z,parent=architecture) {
    box(.32,.035,.24,silver,x,.92,z,parent);
    box(.045,.28,.045,silver,x,1.06,z,parent);
    box(.92,.59,.065,ink,x,1.39,z,parent);
    art(screenTexture,.85,.51,x,1.39,z+.036,parent);
    box(.66,.025,.23,wall,x,.94,z+.43,parent,.015);
    for(let i=0;i<3;i++) box(.57,.003,.008,silver,x,.955,z+.37+i*.06,parent,0);
  }
  function chair(x,z,angle=0) {
    const g=group(architecture,x,.12,z);g.rotation.y=angle;
    cylinder(.28,.28,.07,fabric,0,.5,0,g);box(.57,.48,.09,fabric,0,.85,-.24,g,.05);
    cylinder(.04,.04,.45,silver,0,.24,0,g);
    for(let i=0;i<5;i++){const a=i*Math.PI*.4;limb([0,.05,0],[Math.sin(a)*.3,.04,Math.cos(a)*.3],.025,silver,g);}
    shadow(x,z,.9,.9);
  }
  function desk(x,z) {
    box(2.45,.10,1.08,white,x,.91,z,architecture,.04);
    box(2.25,.035,.85,wood,x,.84,z);
    for(const dx of [-1.03,1.03]) for(const dz of [-.37,.37]) box(.055,.78,.055,silver,x+dx,.47,z+dz);
    monitor(x+.15,z-.2);
    cylinder(.08,.07,.14,white,x-.78,1.03,z+.2); cylinder(.065,.065,.006,wood,x-.78,1.105,z+.2);
    box(.28,.025,.35,paper,x+.92,.98,z+.2,architecture,.005).rotation.y=.2;
    chair(x,z+.9,Math.PI);
    shadow(x,z,2.8,1.6);
  }
  desk(-3.65,-2); desk(-.55,-2.9); desk(2.65,-2.9);
  // 중앙 테이블은 둥근 목재 상판과 인디고 다리로 만들어요.
  box(4.05,.035,2.65,material('#dfe1ed'),-.1,.135,.65,architecture,.018);
  box(3.35,.14,1.65,wood,-.1,.94,.55,architecture,.12);
  box(2.9,.07,1.25,indigo,-.1,.85,.55);
  for(const x of [-1.25,1.05]) box(.18,.75,1.02,indigo,x,.48,.55);
  shadow(-.1,.55,4.25,2.6);
  for(const p of [[-.8,.2],[.45,.85],[1,.1]]) {
    const g=group(architecture,p[0],1.035,p[1]);g.rotation.y=p[0]*.3;
    box(.5,.012,.65,paper,0,0,0,g,.004);
    for(let i=0;i<4;i++) box(.32,.002,.008,wall,0,.01,-.16+i*.075,g,0);
    box(.34,.002,.06,indigo,0,.012,-.24,g,.002);
  }
  for(const x of [-1.1,.95]) {cylinder(.07,.055,.15,white,x,1.09,.75);cylinder(.055,.055,.005,wood,x,1.168,.75);}
  chair(-1.45,1.85,Math.PI); chair(.1,-.65,0);
  // 검증용 자료 카트와 발행대예요.
  box(1.08,.06,.65,white,-4.6,.92,1.4);
  box(1.08,.06,.65,wall,-4.6,.4,1.4);
  for(const x of [-5.05,-4.15]) for(const z of [1.15,1.65]) box(.03,.8,.03,silver,x,.55,z);
  for(let i=0;i<3;i++) box(.53,.045,.36,i===1?indigo:paper,-4.6,.98+i*.05,1.4);
  const pedestal=group(architecture,4.35,.1,2.5);
  box(1.5,.75,1.25,wall,0,.4,0,pedestal,.035);
  box(1.6,.12,1.35,white,0,.85,0,pedestal,.04);
  const openBook=group(pedestal,0,.95,0);openBook.rotation.x=-.18;
  for(const sign of [-1,1]) {
    const page=box(.48,.035,.64,paper,sign*.24,0,0,openBook,.006);page.rotation.z=sign*-.12;
    for(let i=0;i<5;i++) box(.30,.006,.008,wall,sign*.25,.05,-.18+i*.075,openBook,0);
  }
  art(texture((ctx,w,h)=>{ctx.fillStyle='#4f46e5';ctx.font='600 68px Pretendard, sans-serif';ctx.textAlign='center';ctx.fillText('발행한 글',w/2,170);ctx.fillStyle='#71717a';ctx.font='32px Pretendard, sans-serif';ctx.fillText('독자에게 닿는 연구',w/2,235);}),1.2,.6,0,.44,.638,pedestal);
  shadow(4.35,2.5,2,1.8);
  // 바닥의 얇은 경로가 작업 공간을 연결해요.
  for(let i=0;i<8;i++) box(.15,.008,.035,i<5?wall:indigo,1.6+i*.28,.127,3.25,architecture,.003);
  // 낮은 불투명도의 유리 파티션이에요.
  const glass=material('#d9ddec',{transparent:true,opacity:.20,roughness:.15,metalness:.05,depthWrite:false});
  box(.035,1.65,1.9,glass,5.7,.95,-1.15,architecture,.008);
  for(const z of [-2.08,-.22]) box(.035,1.75,.035,silver,5.7,1,z);

  // 공유 리그의 관절로 앉기·집필·대화 자세를 만들어요.
  const homes={lead:[-1.15,1.85,.4,false],editor:[3.15,2.5,.3,false],hrd:[-3.65,-1.1,Math.PI,true],data:[-.55,-2,Math.PI,true],coding:[2.65,-2,Math.PI,true],checker:[-3.85,1.4,.7,false],critic:[.75,2.05,-.2,false],charter:[4.65,-.5,-.4,false]};
  const clothes=['#4f46e5','#4a4c60','#a4a8ba','#ebedf4','#8b90b3','#c0c1df','#676b83','#d0d2df'];
  const faceFront=texture((ctx,w,h)=>{
    ctx.clearRect(0,0,w,h);ctx.fillStyle='#332a29';ctx.beginPath();ctx.ellipse(85,96,5,7,0,0,Math.PI*2);ctx.ellipse(170,96,5,7,0,0,Math.PI*2);ctx.fill();ctx.strokeStyle='#a26d62';ctx.lineWidth=3;ctx.beginPath();ctx.arc(128,125,16,.3,Math.PI-.3);ctx.stroke();
  },256,192);
  roster.forEach((a,index)=>{
    const home=homes[a.key]||[0,2,0,false], actor=group(world,home[0],.13,home[1]);actor.rotation.y=home[2];
    const body=group(actor), shirt=material(clothes[index%clothes.length]), skin=material(a.sprite.skin), hair=material(a.sprite.hair);
    const torso=group(body,0,.99,0);
    sphere(.29,shirt,0,0,0,torso,[1,.98,.65]);
    box(.38,.24,.31,shirt,0,-.2,0,torso,.04);
    cylinder(.07,.085,.15,skin,0,.27,0,torso);
    const head=group(torso,0,.52,0);
    sphere(.235,skin,0,0,0,head,[.89,1.12,.88]);
    sphere(.25,hair,0,.09,-.045,head,[.93,.87,.85]);
    if(['bob','long','tied'].includes(a.sprite.style)) box(.42,a.sprite.style==='long'?.56:.32,.22,hair,0,-.04,-.15,head,.08);
    if(a.sprite.style==='tied') sphere(.12,hair,0,.02,-.29,head,[1,1.2,1]);
    if(a.sprite.style==='curly') for(let k=0;k<9;k++) sphere(.082,hair,Math.sin(k*2.4)*.18,.13+Math.cos(k*1.8)*.05,Math.cos(k*2.4)*.16,head);
    sphere(.048,skin,-.21,-.01,0,head,[.55,1,.6]);sphere(.048,skin,.21,-.01,0,head,[.55,1,.6]);
    sphere(.04,skin,0,-.035,.205,head,[.7,.8,1]);
    art(faceFront,.37,.25,0,-.04,.201,head);
    if(['editor','coding','checker'].includes(a.key)) {
      for(const x of [-.095,.095]) {const g=mesh(geometry('glasses',()=>new T.TorusGeometry(.07,.009,6,16)),ink,x,.005,.21,head);g.scale.y=.8;}
      limb([-.03,.005,.213],[.03,.005,.213],.007,ink,head);
    }
    // 셔츠의 여밈을 표현해요.
    box(.03,.31,.01,index===0?white:wall,0,-.02,.185,torso,.003);
    const arms=[];
    for(const side of [-1,1]) {
      const shoulder=group(torso,side*.25,.10,0);
      const upper=group(shoulder);limb([0,0,0],[side*.06,-.27,0],.075,shirt,upper);
      const elbow=group(upper,side*.06,-.27,0);limb([0,0,0],[0,-.24,0],.055,skin,elbow);
      sphere(.067,skin,0,-.25,0,elbow,[.8,1.1,.7]);arms.push({shoulder,upper,elbow,side});
    }
    const legs=[];
    for(const side of [-1,1]) {
      const hip=group(body,side*.105,.65,0);limb([0,0,0],[0,-.27,0],.083,ink,hip);
      const knee=group(hip,0,-.27,0);limb([0,0,0],[0,-.27,0],.065,ink,knee);
      box(.17,.095,.27,material('#4a4b56'),0,-.29,.055,knee,.035);legs.push({hip,knee,side});
    }
    const ring=mesh(geometry('ring',()=>new T.TorusGeometry(.39,.018,6,40)),indigo,0,.015,0,actor);ring.rotation.x=-Math.PI/2;ring.visible=false;ring.castShadow=false;
    shadow(0,0,.95,.8,actor);
    batchRigidParts(actor);
    if(lowDetail) flattenBody(body);
    actor.traverse(m=>{if(m.isMesh){m.userData.agent=a.key;hits.push(m);}});
    const label=document.createElement('span');label.className='tc-ls-label';label.textContent=a.name;labels.append(label);
    actors.set(a.key,{actor,body,torso,head,arms,legs,ring,label,home,index,position:new T.Vector3(home[0],.13,home[1]),angle:home[2]});
  });

  // 관절 그룹은 보존하고 같은 부위의 고정된 조각만 합쳐요.
  function batchRigidParts(parent) {
    parent.children.filter(c=>c.isGroup).forEach(batchRigidParts);
    const buckets=new Map();
    parent.children.filter(c=>c.isMesh).forEach(o=>{
      o.updateMatrix();const part=batchGeometry(o,o.matrix);
      const key=`${part.mat.uuid}:${o.castShadow}:${o.receiveShadow}:${o.visible}`;
      if(!buckets.has(key))buckets.set(key,{objects:[],geos:[],mat:part.mat});
      buckets.get(key).objects.push(o);buckets.get(key).geos.push(part.geo);
    });
    for(const b of buckets.values()) {
      if(b.objects.length<2){b.geos.forEach(g=>g.dispose());continue;}
      const g=mergeGeometries(b.geos,false);b.geos.forEach(a=>a.dispose());
      if(!g)continue;
      const first=b.objects[0],o=new T.Mesh(g,b.mat);o.castShadow=first.castShadow;o.receiveShadow=first.receiveShadow;
      o.visible=first.visible;geos.set(g.uuid,g);b.objects.forEach(m=>parent.remove(m));parent.add(o);
    }
  }
  function flattenBody(body) {
    // 모바일은 관절 대신 전체 몸체를 합친 경량 모형을 움직여요.
    body.updateWorldMatrix(true,true);
    const inverse=body.matrixWorld.clone().invert(),buckets=new Map();
    body.traverse(o=>{
      if(!o.isMesh)return;
      const matrix=inverse.clone().multiply(o.matrixWorld),part=batchGeometry(o,matrix);
      const key=part.mat.uuid;
      if(!buckets.has(key))buckets.set(key,{mat:part.mat,geos:[]});
      buckets.get(key).geos.push(part.geo);
    });
    body.clear();
    for(const b of buckets.values()){
      const geo=mergeGeometries(b.geos,false);b.geos.forEach(g=>g.dispose());
      if(geo){geos.set(geo.uuid,geo);const o=new T.Mesh(geo,b.mat);o.receiveShadow=true;body.add(o);}
    }
  }

  // 고정물은 재질별로 합치고 사람은 개별 관절로 움직여요.
  architecture.updateMatrixWorld(true);
  const batches=new Map();
  architecture.traverse(o=>{
    if(!o.isMesh) return;
    const part=batchGeometry(o,o.matrixWorld);
    const key=`${part.mat.uuid}:${o.castShadow}:${o.receiveShadow}`;
    if(!batches.has(key)) batches.set(key,{geos:[],mat:part.mat,cast:o.castShadow,receive:o.receiveShadow});
    batches.get(key).geos.push(part.geo);
  });
  architecture.clear();
  for(const batch of batches.values()) {
    const g=mergeGeometries(batch.geos,false);batch.geos.forEach(a=>a.dispose());
    if(!g) throw new Error('연구실 모델을 합치지 못했어요.');
    geos.set(g.uuid,g);const o=new T.Mesh(g,batch.mat);o.castShadow=batch.cast;o.receiveShadow=batch.receive;architecture.add(o);
  }

  function select(key) {
    selected=actors.has(key)?key:'';
    if(!meeting) {
      const p=actors.get(selected)?.actor.position;
      lookTarget.set(p?p.x*.48:0,selected ? .9 : 1.15,p?p.z*.36:0);
      targetSize=selected?14.0:20.0;
    }
    needRender=true;
  }
  function setMeeting(key) {
    meeting=actors.has(key)?key:'';
    lookTarget.set(0,1.15,.4); targetSize=meeting?14.0:20.0;
    if(!meeting) select(selected);
    needRender=true;
  }
  function reset() { targetYaw=baseYaw;targetTilt=baseTilt;targetSize=20.0;lookTarget.set(0,1.15,0);needRender=true; }
  function zoom(factor) {targetSize=T.MathUtils.clamp(targetSize*factor,9.5,19);needRender=true;}
  function cameraUpdate() {
    const fast=reducedMotion?1:.14;
    yaw+= (targetYaw-yaw)*fast;tilt+=(targetTilt-tilt)*fast;size+=(targetSize-size)*fast;look.lerp(lookTarget,fast);
    const w=canvas.clientWidth,h=canvas.clientHeight,aspect=w/h,vertical=size/(Math.max(1,aspect*.94));
    camera.left=-vertical*aspect/2;camera.right=vertical*aspect/2;camera.top=vertical/2;camera.bottom=-vertical/2;camera.updateProjectionMatrix();
    const r=22;camera.position.set(look.x+Math.sin(yaw)*Math.cos(tilt)*r,look.y+Math.sin(tilt)*r,look.z+Math.cos(yaw)*Math.cos(tilt)*r);camera.lookAt(look);
    return Math.abs(targetYaw-yaw)+Math.abs(targetTilt-tilt)+Math.abs(targetSize-size)+look.distanceTo(lookTarget)>.002;
  }
  let lastTick=performance.now(),lastShadow=0;
  function pose(p,dt) {
    const {actor,body,torso,head,arms,legs,home,index}=p;
    const angle=index/8*Math.PI*2;
    const goal=meeting?new T.Vector3(Math.sin(angle)*2.1,.13,.55+Math.cos(angle)*1.5):p.position;
    const moved=actor.position.distanceTo(goal)>.01;
    actor.position.lerp(goal,reducedMotion?1:1-Math.exp(-dt*4));
    let desired=meeting?Math.atan2(-goal.x,.55-goal.z):p.angle;
    actor.rotation.y+=T.MathUtils.euclideanModulo(desired-actor.rotation.y+Math.PI,Math.PI*2)-Math.PI;
    const seated=home[3]&&!meeting&&!lowDetail;
    const working=active===roster[index]?.key&&!meeting;
    const talking=meeting===roster[index]?.key;
    const t=animationTime+index*1.7, idle=paused?0:Math.sin(t*1.35)*.012;
    body.position.y=seated?-.29:idle;
    torso.rotation.x=working&&seated?.08:0;
    head.rotation.z=paused?0:Math.sin(t*.45)*.025;
    head.rotation.x=working?.08:talking?-.04:0;
    if(!lowDetail) arms.forEach(({upper,elbow,side})=>{
      upper.rotation.z=side*(working?.10:.08);
      upper.rotation.x=seated?-1.0:talking&&side===1?-.85:0;
      elbow.rotation.x=seated?-.65:talking&&side===1?-.75:-.15;
      if(!paused&&working) elbow.rotation.x+=Math.sin(t*6+side)*.06;
      if(!paused&&talking&&side===1) upper.rotation.z+=Math.sin(t*2)*.12;
      if(moved&&!paused) upper.rotation.x+=Math.sin(t*7)*.25*side;
    });
    if(!lowDetail) legs.forEach(({hip,knee,side})=>{hip.rotation.x=seated?-Math.PI/2:moved&&!paused?Math.sin(t*7)*.2*side:0;knee.rotation.x=seated?Math.PI/2:0;});
    const key=roster[index]?.key;
    p.ring.visible=selected===key||active===key||meeting===key;
    p.label.classList.toggle('is-selected',selected===key||meeting===key);
    p.label.classList.toggle('is-active',active===key&&!meeting);
    projected.set(0,1.95,0);actor.localToWorld(projected);projected.project(camera);
    p.label.style.left=`${(projected.x*.5+.5)*canvas.clientWidth}px`;p.label.style.top=`${(-projected.y*.5+.5)*canvas.clientHeight}px`;
    return moved;
  }
  function render(now) {
    frame=0;if(disposed||!shown)return;
    if(now-previousFrame<32){frame=requestAnimationFrame(render);return;}
    const dt=Math.min((now-lastTick)/1000,.06);lastTick=now;previousFrame=now;
    if(!paused) animationTime+=dt;
    const cameraMoving=cameraUpdate();let moving=false;
    actors.forEach(p=>{moving=pose(p,dt)||moving;});
    if(moving&&now-lastShadow>250){renderer.shadowMap.needsUpdate=true;lastShadow=now;}
    if(!paused||needRender||cameraMoving||moving){renderer.render(world,camera);needRender=false;}
    if(!paused||cameraMoving||moving||needRender) frame=requestAnimationFrame(render);
  }
  function wake(){needRender=true;renderer.shadowMap.needsUpdate=true;if(shown&&!frame&&!disposed){lastTick=performance.now();frame=requestAnimationFrame(render);}}
  const resize=new ResizeObserver(()=>{renderer.setSize(canvas.parentElement.clientWidth,canvas.parentElement.clientHeight,false);wake();});resize.observe(canvas.parentElement);
  const ray=new T.Raycaster(),mouse=new T.Vector2();let pointer=null,hovered='';
  function hit(event) {
    const r=canvas.getBoundingClientRect();mouse.set((event.clientX-r.left)/r.width*2-1,-(event.clientY-r.top)/r.height*2+1);
    ray.setFromCamera(mouse,camera);return ray.intersectObjects(hits,false)[0]?.object.userData.agent||'';
  }
  function down(e){if(e.button!==0)return;pointer={id:e.pointerId,x:e.clientX,y:e.clientY,lastX:e.clientX,moved:false};canvas.setPointerCapture(e.pointerId);}
  function move(e){
    if(pointer&&pointer.id===e.pointerId){const dx=e.clientX-pointer.lastX;pointer.lastX=e.clientX;if(Math.abs(e.clientX-pointer.x)>5)pointer.moved=true;if(pointer.moved){targetYaw=T.MathUtils.clamp(targetYaw+dx*.004,.18,1.17);wake();}}
    else if(e.pointerType==='mouse'){const key=hit(e);if(key!==hovered){hovered=key;actors.forEach((p,k)=>p.label.classList.toggle('is-hovered',k===key));canvas.style.cursor=key?'pointer':'grab';wake();}}
  }
  function up(e){if(pointer?.id!==e.pointerId)return;const moved=pointer.moved||Math.abs(e.clientY-pointer.y)>8;pointer=null;if(!moved){const key=hit(e);if(key)onSelect(key);}}
  function cancel(){pointer=null;}
  function leave(){if(!pointer){hovered='';actors.forEach(p=>p.label.classList.remove('is-hovered'));wake();}}
  function keyboard(e){
    if(e.key==='ArrowLeft')targetYaw=T.MathUtils.clamp(targetYaw-.10,.18,1.17);
    else if(e.key==='ArrowRight')targetYaw=T.MathUtils.clamp(targetYaw+.10,.18,1.17);
    else if(e.key==='+'||e.key==='=')zoom(.9);
    else if(e.key==='-')zoom(1.1);
    else if(e.key==='Escape'){reset();onSelect('');}
    else return;e.preventDefault();wake();
  }
  function contextLost(e){e.preventDefault();onFailure();}
  canvas.addEventListener('pointerdown',down);canvas.addEventListener('pointermove',move);canvas.addEventListener('pointerup',up);canvas.addEventListener('pointercancel',cancel);canvas.addEventListener('pointerleave',leave);canvas.addEventListener('keydown',keyboard);canvas.addEventListener('webglcontextlost',contextLost);
  function dispose(){
    if(disposed)return;disposed=true;cancelAnimationFrame(frame);resize.disconnect();
    canvas.removeEventListener('pointerdown',down);canvas.removeEventListener('pointermove',move);canvas.removeEventListener('pointerup',up);canvas.removeEventListener('pointercancel',cancel);canvas.removeEventListener('pointerleave',leave);canvas.removeEventListener('keydown',keyboard);canvas.removeEventListener('webglcontextlost',contextLost);
    geos.forEach(g=>g.dispose());mats.forEach(m=>m.dispose());textures.forEach(t=>t.dispose());renderer.dispose();labels.replaceChildren();
  }
  wake();
  return {
    select(key){select(key);wake();},setMeeting(key){setMeeting(key);wake();},
    setActive(key){active=actors.has(key)?key:'';wake();},
    setPaused(value){paused=value;wake();},
    setVisible(value){shown=value;if(value)wake();else{cancelAnimationFrame(frame);frame=0;}},
    zoom(factor){zoom(factor);wake();},reset(){reset();wake();},dispose,
    stats(){return {drawCalls:renderer.info.render.calls,triangles:renderer.info.render.triangles,people:actors.size,geometries:renderer.info.memory.geometries,textures:renderer.info.memory.textures};}
  };
}
