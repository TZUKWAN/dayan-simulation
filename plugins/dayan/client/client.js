/**
 * 大衍 DAYAN for DSH — client entry.
 * 侧边栏「大衍」条目 → 主面板分栏：
 *   左：DSH 原生对话（会话 retain + nativeKit.SessionProvider + renderSlot，
 *       消息流用宿主 'conversation.content' 原生槽）——AI 助手即 DSH 本体，
 *       经 host 注册的 dayan 工具（list_models/run/collect/…）驱动平台；
 *   右：工作台 iframe（127.0.0.1:8899 原样嵌入，功能不阉割），可折叠。
 * 模式实证来源：ares（SessionProvider/renderSlot/children 槽声明、
 * nativeConversationLayout、inputActions.setDraft）与 designcraft
 * （sidebar.panellist、locale、main slot 清理协议）。
 */
window.__ModuleLoader__.load({
	id: 'dayan',
	factory(require) {
		const React = require('react');
		const { conversationPhase } = require('@deepseek-ai/dsh-client-ui-conversation');
		const h = React.createElement;
		const PKG_ID = 'dayan';
		const BACKEND_URL = 'http://127.0.0.1:8899';

		const DICT = {
			zh: { nav: '大衍' },
			en: { nav: 'Dayan' }
		};

		const STYLE = {
			center: {
				height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center',
				justifyContent: 'center', gap: 14, padding: 24, textAlign: 'center', color: 'inherit'
			},
			logo: { fontSize: 44, lineHeight: 1, opacity: 0.9 },
			title: { fontSize: 20, fontWeight: 600, letterSpacing: 2 },
			hint: { fontSize: 13, opacity: 0.72, maxWidth: 460 },
			tip: { fontSize: 12, opacity: 0.5, maxWidth: 460 },
			button: {
				marginTop: 6, padding: '9px 26px', fontSize: 14, borderRadius: 8, border: '1px solid #3A4652',
				background: 'rgba(128,128,128,.12)', color: 'inherit', cursor: 'pointer'
			},
			error: { fontSize: 13, color: '#E07B72', maxWidth: 460 },
			split: { height: '100%', display: 'flex', minHeight: 0, minWidth: 0, position: 'relative' },
			chatPane: { flex: '0 0 var(--dayan-chat-width,42%)', minWidth: 0, borderRight: '1px solid #2A3440', display: 'flex', flexDirection: 'column', minHeight: 0, background: 'transparent' },
			chatHead: { padding: '10px 14px', fontSize: 12, letterSpacing: 1, color: 'inherit', borderBottom: '1px solid #2A3440', display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
			chatBody: { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' },
			chatStatus: { flex: 1, display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'center', justifyContent: 'center', padding: 20, textAlign: 'center', color: 'inherit', fontSize: 13 },
			workPane: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 0, position: 'relative' },
			workHead: { padding: '10px 14px', fontSize: 12, letterSpacing: 1, color: 'inherit', borderBottom: '1px solid #2A3440', display: 'flex', gap: 10, justifyContent: 'space-between', alignItems: 'center' },
			collapse: { fontSize: 12, color: 'inherit', background: 'none', border: '1px solid #2A3440', borderRadius: 6, padding: '3px 10px', cursor: 'pointer' },
			welcome: { padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 8 },
			welcomeTitle: { fontSize: 14, fontWeight: 600, color: 'inherit' },
			welcomeSub: { fontSize: 12, color: 'inherit' },
			shortcut: {
				textAlign: 'left', fontSize: 13, padding: '8px 12px', borderRadius: 8,
				border: '1px solid #2A3440', background: 'rgba(128,128,128,.08)', color: 'inherit', cursor: 'pointer'
			}
		};

		const SHORTCUTS = [
			['看模型目录', '用 dayan 工具列出传染病主题的模型，我要挑一个来跑'],
			['跑一次仿真', '用 dayan 工具先取 NET052 的参数合同，然后按合同跑 200 步仿真，把关键序列和 manifest 摘要给我'],
			['采集真实数据', '用 dayan 工具看看人口主题有哪些 live 数据源，然后执行 pop_employment_wb 预设采集中国 2018-2024 人口'],
			['政策对比', '用 dayan 工具跑 NET052 基线 200 步，再跑一个在第 5 步把 beta 乘 0.7 的干预臂，对比两条感染曲线']
		];

		function ChatWelcome({ onPick }) {
			return h('div', { style: STYLE.welcome },
				h('div', { style: STYLE.welcomeTitle }, '大衍研究助手（DSH 原生 AI）'),
				h('div', { style: STYLE.welcomeSub }, '对话由 DSH 会话驱动；平台能力经 dayan 工具执行，结果可直接在工作台查看。'),
				SHORTCUTS.map(([label, text]) => h('button', {
					type: 'button', key: label, style: STYLE.shortcut,
					onClick: () => onPick(text)
				}, label)));
		}

		// 'dayan.chat' 子槽体：宿主注入 useSession/useConversation/renderFactorySlot/inputActions
		function ChatBody(props) {
			const session = props.useSession ? props.useSession((v) => v) : null;
			const conversation = props.useConversation ? props.useConversation((v) => v) : null;
			const matches = !!props.dayanSessionId && session?.sessionId === props.dayanSessionId && !session?.removed;
			const phase = matches && conversation ? conversationPhase(session, conversation) : 'settling';
			const layout = { phase: session?.openState === 'open' ? 'active' : 'settling', hero: false, variant: 'embedded' };
            React.useEffect(()=>{
                const receive=event=>{
                    const frame=props.workbenchRef?.current;
                    if(!matches||event.data?.sessionId!==props.dayanSessionId||!frame||frame.dataset.dayanSessionId!==props.dayanSessionId||event.source!==frame.contentWindow||event.origin!==new URL(frame.src).origin)return;
                    if(event.data?.type==='dayan:native-draft'&&typeof event.data.text==='string')props.inputActions?.setDraft(event.data.text.slice(0,20000));
                };
                window.addEventListener('message',receive);return ()=>window.removeEventListener('message',receive);
            },[props.inputActions,props.dayanSessionId,props.workbenchRef,matches]);
			const pick = (text) => { try { props.inputActions?.setDraft(text); } catch { } };

			if(!matches || session?.openState!=='open')return h('div', { style: STYLE.chatStatus, role: 'status' }, '正在核验大衍专属对话，未显示其他会话。');
			const stream = props.renderFactorySlot
				? props.renderFactorySlot('conversation.content', layout, {
					fallback: h('div', { style: STYLE.chatStatus, role: 'status' }, 'DSH 原生对话组件尚未就绪。')
				})
				: h('div', { style: STYLE.chatStatus, role: 'status' }, '原生对话槽未注入（宿主版本不兼容）。');

			return h('div', { style: STYLE.chatBody },
				phase === 'blank' ? h(ChatWelcome, { onPick: pick }) : null,
				h('div', { style: { flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' } }, stream));
		}

		function Checking() {
			return h('div', { style: STYLE.center },
				h('div', { style: STYLE.title }, '大衍 DAYAN'),
				h('div', { style: STYLE.hint }, '正在探测本机后端…'));
		}

		function BackendOffline({ onStart, starting, error, compact }) {
			return h('div', { style: { ...STYLE.center, ...(compact ? { gap: 10 } : {}) } },
				h('div', { style: compact ? { fontSize: 28 } : STYLE.logo }, '☰'),
				h('div', { style: compact ? { fontSize: 16, fontWeight: 600 } : STYLE.title }, '大衍 DAYAN'),
				h('div', { style: STYLE.hint }, compact ? '工作台后端未启动' : '45 源真实数据采集 · 456 模型仿真 · 政策模拟与研究报告'),
				starting
					? h('div', { style: STYLE.hint }, '后端启动中，通常 5–15 秒…')
					: h('button', { style: STYLE.button, type: 'button', onClick: onStart }, '启动工作台后端'),
				error ? h('div', { style: STYLE.error }, error) : null,
				compact ? null : h('div', { style: STYLE.tip }, '后端在线时右侧将完整嵌入工作台；也可在外部浏览器打开 ',
					h('a', { href: BACKEND_URL, target: '_blank', rel: 'noreferrer' }, BACKEND_URL)));
		}

		function apply(ctx) {
			ctx.effect(() => ctx.locale.register(PKG_ID, DICT), 'dayan: dictionaries');
			ctx.effect(() => {
				const tag = document.createElement('style');
				tag.dataset.pluginCss = PKG_ID + '/entry.css';
				tag.textContent = '.dayanPanelMount{height:100%;min-height:0}.dayanSplitHandle{flex:0 0 8px;align-self:stretch;display:grid;place-items:center;cursor:col-resize;touch-action:none;user-select:none;z-index:2;outline-offset:-2px}.dayanSplitHandle>span{width:2px;height:38px;background:currentColor;border-radius:2px;opacity:.35}.dayanSplitHandle:hover,.dayanSplitHandle:focus-visible,.dayanPanelMount[data-resizing="true"] .dayanSplitHandle{background:rgba(128,128,128,.16);outline:1px solid rgba(128,128,128,.45)}';
				document.head.appendChild(tag);
				return () => { try { tag.remove(); } catch { } };
			}, 'dayan: entry styles');

			ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({
				name: 'sidebar.panellist', id: 'dayan', order: 7, locale: PKG_ID, label: () => ctx.locale.bind(PKG_ID)('nav')
			}, () => h('svg', { width: 17, height: 17, viewBox: '0 0 28 28', fill: 'none', 'aria-hidden': true },
				h('circle', { cx: 14, cy: 14, r: 11, stroke: 'currentColor', 'stroke-width': 1.8 }),
				h('circle', { cx: 14, cy: 14, r: 5.5, stroke: 'currentColor', 'stroke-width': 1.6 }),
				h('circle', { cx: 14, cy: 3, r: 1.8, fill: 'currentColor' }),
				h('circle', { cx: 22.6, cy: 20.6, r: 1.4, fill: 'currentColor' }),
				h('circle', { cx: 5.4, cy: 20.6, r: 1.1, fill: 'currentColor' }))));

			// Keep the project's own conversation independent of every ordinary main-view selection.
            const services = {}, serviceListeners = new Set();let serviceVersion=0;
            const subscribeServices = callback => {serviceListeners.add(callback);return ()=>serviceListeners.delete(callback);};
            for (const name of ['sessions']) {
                ctx.inject([name], scope => {
                    services[name]=scope[name];serviceVersion++;for(const callback of serviceListeners)callback();
                    scope.effect(()=>()=>{if(services[name]===scope[name]){delete services[name];serviceVersion++;for(const callback of serviceListeners)callback();}},'dayan: '+name+' lifetime');
                });
            }

			// main 面板：左 = DSH 原生对话，右 = 工作台 iframe
			function Panel(props) {
				const nativeKit = props || {};
				const [connection, setConn] = React.useState(null);
				const [chatError, setChatError] = React.useState(null);
				const [backend, setBackend] = React.useState('checking');
				const [starting, setStarting] = React.useState(false);
				const [backendError, setBackendError] = React.useState(null);
				const [chatCollapsed, setChatCollapsed] = React.useState(false);
                const [retryConnection,setRetryConnection]=React.useState(0);
                const workbenchRef=React.useRef(null);
                const splitRootRef=React.useRef(null),splitterRef=React.useRef(null),dragRef=React.useRef(null),splitRaf=React.useRef(null);
                const [chatWidth,setChatWidth]=React.useState(42),[dragging,setDragging]=React.useState(false);
                const widthRef=React.useRef(42);
                React.useEffect(()=>{
                    const expand=event=>{
                        const frame=workbenchRef.current;
                        if(frame&&event.data?.sessionId===frame.dataset.dayanSessionId&&event.source===frame.contentWindow&&event.origin===new URL(frame.src).origin&&event.data?.type==='dayan:native-draft')setChatCollapsed(false);
                    };
                    window.addEventListener('message',expand);return ()=>window.removeEventListener('message',expand);
                },[]);

                const serviceRevision=React.useSyncExternalStore(subscribeServices,()=>serviceVersion,()=>serviceVersion);
                const [backendConfig,setBackendConfig]=React.useState(null);
                const conn=connection?.serviceRevision===serviceRevision&&connection?.projectRoot===backendConfig?.projectRoot?connection:null;
                const backendUrl=backendConfig?.url||BACKEND_URL;
                const splitStorageKey=backendConfig?.projectRoot?'dayan_pane_split_v1:'+backendConfig.projectRoot.replace(/\\/g,'/').replace(/\/+$/,'').toLowerCase():null;
                function clampedWidth(percent){
                    const total=splitRootRef.current?.getBoundingClientRect().width||0;
                    if(total<=8)return 42;
                    const available=total-8,minChat=Math.min(280,available*.4),minWorkbench=Math.min(360,available*.4);
                    return Math.max(minChat,Math.min(available-minWorkbench,total*percent/100))/total*100;
                }
                function paintWidth(percent){
                    const value=clampedWidth(percent);widthRef.current=value;
                    splitRootRef.current?.style.setProperty('--dayan-chat-width',value+'%');
                    splitterRef.current?.setAttribute('aria-valuenow',String(Math.round(value)));
                    return value;
                }
                function saveWidth(percent){
                    const value=paintWidth(percent);setChatWidth(value);
                    if(splitStorageKey)try{localStorage.setItem(splitStorageKey,String(value));}catch{}
                }
                function dragWidth(event){
                    const rect=splitRootRef.current?.getBoundingClientRect(),drag=dragRef.current;
                    return rect?.width&&drag?drag.startPercent+(event.clientX-drag.startX)/rect.width*100:widthRef.current;
                }
                function finishResize(event){
                    const drag=dragRef.current;if(!drag)return;
                    const value=event?.type==='pointerup'?dragWidth(event):drag.pending;
                    dragRef.current=null;
                    if(splitRaf.current!==null){cancelAnimationFrame(splitRaf.current);splitRaf.current=null;}
                    saveWidth(value);
                    setDragging(false);
                    try{if(drag.element.hasPointerCapture(drag.id))drag.element.releasePointerCapture(drag.id);}catch{}
                }
                React.useEffect(()=>{
                    let saved=42;
                    if(splitStorageKey)try{const value=Number(localStorage.getItem(splitStorageKey));if(Number.isFinite(value)&&value>=10&&value<=90)saved=value;}catch{}
                    const value=paintWidth(saved);setChatWidth(value);
                },[splitStorageKey]);
                React.useEffect(()=>{
                    const element=splitRootRef.current;if(!element)return;
                    const observer=new ResizeObserver(()=>{if(!dragRef.current){const value=paintWidth(widthRef.current);setChatWidth(previous=>Math.abs(previous-value)>.05?value:previous);}});
                    observer.observe(element);
                    return()=>{observer.disconnect();if(splitRaf.current!==null)cancelAnimationFrame(splitRaf.current);};
                },[]);
                React.useEffect(()=>{
                    let active=true,lease=null;const controller=new AbortController();
                    setConn(null);setChatError(null);
                    const sessions=services.sessions;
                    if(!sessions||!backendConfig)return ()=>{active=false;};
                    (async()=>{
                        const {openProjectConversation}=await import('/dayan/api/session-binding.js?v=project-session-v2');
                        const response=await fetch('/dayan/api/native-session',{cache:'no-store',signal:controller.signal});
                        const result=await response.json();
                        if(!response.ok||!result.ok)throw new Error(result.error||'大衍专属对话身份读取失败');
                        const opened=await openProjectConversation({sessions,record:result.session,projectRoot:backendConfig.projectRoot,signal:controller.signal});
                        lease=opened.reference;
                        if(active)setConn({...opened,projectRoot:backendConfig.projectRoot,serviceRevision});
                        else lease.release();
                    })().catch(cause=>{if(active&&!controller.signal.aborted)setChatError(String(cause?.message||cause));});
                    return ()=>{active=false;controller.abort();lease?.release();};
                },[serviceRevision,backendConfig,retryConnection]);

				React.useEffect(() => {
					let active = true;
					fetch('/dayan/api/health', { cache: 'no-store' })
						.then((r) => r.json())
						.then((v) => { if (active) {setBackend(v.online ? 'online' : 'offline');setBackendConfig(v);} })
						.catch(() => { if (active) setBackend('offline'); });
					return () => { active = false; };
				}, []);

				const startBackend = async () => {
					setStarting(true); setBackendError(null);
					try {
						const response = await fetch('/dayan/api/backend/start', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' });
						const value = await response.json();
						if (value.ok && value.online) {setBackend('online');setBackendConfig(current=>({...current,...value}));}
						else setBackendError(value.error || '启动失败，请查看 data/server_dsh.log');
					} catch (cause) { setBackendError(String(cause?.message || cause)); }
					setStarting(false);
				};

				const chat = nativeKit?.SessionProvider && nativeKit?.renderSlot && conn
					? h(nativeKit.SessionProvider, { key: conn.sessionId, session: conn.reference },
						nativeKit.renderSlot('dayan.chat', { inputContextReady: true, dayanSessionId: conn.sessionId, workbenchRef }))
					: h('div', { style: STYLE.chatStatus, role: conn ? 'status' : 'alert' },
						h('div', null, conn ? '正在加载 DSH 原生对话…' : (chatError || '正在连接 DSH 原生会话…')),
						h('div', { style: STYLE.hint }, '仅连接本项目的大衍研究对话；连接失败不会回退到其他聊天。'),
                        chatError?h('button',{type:'button',style:STYLE.collapse,onClick:()=>setRetryConnection(n=>n+1)},'重试连接'):null);

				const workbench = backend === 'online'
					? conn ? h('iframe', {
						src: backendUrl + '/?' + new URLSearchParams({embed:'dsh',dsh_session:conn.sessionId,parent_origin:location.origin}), ref:workbenchRef, 'data-dayan-workbench':'true', 'data-dayan-session-id':conn.sessionId, title: '大衍 DAYAN 工作台',
						style: { width: '100%', flex: 1, minHeight: 0, border: '0', display: 'block', pointerEvents:dragging?'none':undefined }
					}) : h('div',{style:STYLE.chatStatus,role:'status'},'等待本项目专属对话连接后同步研究结果。')
					: h(BackendOffline, { onStart: startBackend, starting, error: backendError, compact: true });

				return h('div', { ref:splitRootRef,className: 'dayanPanelMount', style: {...STYLE.split,'--dayan-chat-width':chatWidth+'%',userSelect:dragging?'none':undefined}, 'data-dayan-bound-session':conn?.sessionId||'', 'data-resizing':String(dragging) },
					h('div', { style: { ...STYLE.chatPane, ...(chatCollapsed ? { display: 'none' } : {}) } },
						h('div', { style: STYLE.chatHead },
						h('span', {title:conn?.sessionId||'连接中'}, '大衍专属研究对话'),
							h('button', { type: 'button', style: STYLE.collapse, onClick: () => setChatCollapsed(true) }, '收起')),
						h('div', { style: { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' } }, chat)),
                    chatCollapsed?null:h('div',{
                        ref:splitterRef,className:'dayanSplitHandle',role:'separator',tabIndex:0,
                        'aria-label':'调整对话与工作台宽度','aria-orientation':'vertical','aria-valuemin':10,'aria-valuemax':90,'aria-valuenow':Math.round(chatWidth),
                        title:'拖动调整对话与工作台宽度，双击恢复默认；方向键微调',
                        onPointerDown:event=>{if(event.button!==0)return;event.preventDefault();event.currentTarget.focus({preventScroll:true});event.currentTarget.setPointerCapture(event.pointerId);dragRef.current={id:event.pointerId,element:event.currentTarget,pending:widthRef.current,startX:event.clientX,startPercent:widthRef.current};setDragging(true);},
                        onPointerMove:event=>{const drag=dragRef.current;if(!drag||drag.id!==event.pointerId)return;drag.pending=dragWidth(event);if(splitRaf.current===null)splitRaf.current=requestAnimationFrame(()=>{splitRaf.current=null;if(dragRef.current)paintWidth(dragRef.current.pending);});},
                        onPointerUp:finishResize,onPointerCancel:finishResize,onLostPointerCapture:finishResize,
                        onDoubleClick:()=>saveWidth(42),
                        onKeyDown:event=>{const steps={ArrowLeft:-2,ArrowRight:2};if(event.key in steps){event.preventDefault();saveWidth(widthRef.current+steps[event.key]*(event.shiftKey?2.5:1));}else if(event.key==='Home'||event.key==='End'){event.preventDefault();saveWidth(event.key==='Home'?0:100);}}
                    },h('span',{'aria-hidden':true})),
					h('div', { style: STYLE.workPane },
						h('div', { style: STYLE.workHead },
							h('span', null, '工作台（完整界面）'),
							chatCollapsed ? h('button', { type: 'button', style: STYLE.collapse, onClick: () => setChatCollapsed(false) }, '展开对话') : null),
						h('div', { style: { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' } }, workbench)));
			}

			ctx.slots.inject('dayan.chat', () => ctx.slots.register({ name: 'dayan.chat' }, ChatBody));

			ctx.slots.inject('main', () => {
				const off = ctx.slots.register({
					name: 'main', key: 'dayan', locale: PKG_ID,
					children: { 'dayan.chat': { kind: 'single', scope: 'session' } }
				}, (props) => h(Panel, props));
				return () => {
					const layout = ctx.get('layout');
					if (layout?.panelInfo?.getSnapshot?.().activePanelId === 'dayan') layout.selectPanel(null);
					if (typeof off === 'function') off();
				};
			});
		}

		return { inject: ['slots', 'locale'], apply };
	}
});
