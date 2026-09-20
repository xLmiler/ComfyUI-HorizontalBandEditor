import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "HorizontalBandEditor";
const VUE_NODES_SETTING = "Comfy.VueNodes.Enabled";

function isNodes2Enabled() {
    try {
        const v = app.extensionManager?.setting?.get?.(VUE_NODES_SETTING);
        if (v !== undefined) return v === true || v === "true" || v === 1;
    } catch (_) {}
    try {
        const v = app.ui?.settings?.getSettingValue?.(VUE_NODES_SETTING);
        return v === true || v === "true" || v === 1;
    } catch (_) {}
    return false;
}

function getWidget(node, ...names) {
    return node.widgets?.find((w) => names.includes(w.name));
}

function setWidgetValue(widget, value, node) {
    if (!widget) return;
    widget.value = value;
    try { widget.callback?.(value, app.canvas, node, [0, 0], {}); } catch (_) {}
    node.setDirtyCanvas?.(true, true);
}

function hideWidget(widget) {
    if (!widget) return;
    widget.computeSize = () => [0, 0];
    widget.hidden = true;
    widget.visible = false;
    widget.type = "hidden";
    widget.draw = () => {};
    widget.serialize = true;
    widget.options = { ...(widget.options || {}), hidden: true };
}

function bindWidgetSync(widget, callback) {
    if (!widget) return;
    const original = widget.callback;
    widget.callback = function (...args) {
        const out = original?.apply(this, args);
        callback?.();
        return out;
    };
}

function makeViewUrl(value) {
    const params = new URLSearchParams();
    params.set("filename", String(value || ""));
    params.set("type", "input");
    params.set("subfolder", "");
    return api.apiURL(`/view?${params.toString()}`);
}

function getConnectedLoadImage(node) {
    if (!node?.inputs?.length || !app.graph) return null;
    for (const input of node.inputs) {
        if (!input || !["输入图像", "input_image"].includes(input.name) || input.link == null) continue;
        const link = app.graph.links?.[input.link];
        const upstream = link?.origin_id != null ? app.graph.getNodeById?.(link.origin_id) : null;
        if (!upstream) continue;
        const imageWidget = upstream.widgets?.find((w) => w.name === "image");
        if (imageWidget?.value) {
            return {
                filename: String(imageWidget.value),
                title: upstream.title || upstream.type || "加载图像",
            };
        }
    }
    return null;
}

function parseRegions(raw) {
    try {
        const data = JSON.parse(String(raw || "[]"));
        if (!Array.isArray(data)) return [];
        return data.map((v) => Array.isArray(v) ? [Number(v[0]), Number(v[1])] : [Number(v?.top), Number(v?.bottom)])
            .filter(([a, b]) => Number.isFinite(a) && Number.isFinite(b) && b > a);
    } catch (_) {
        return [];
    }
}

function normalizeRegions(regions, height = Infinity) {
    const valid = regions.map(([a, b]) => [Math.max(0, Math.round(a)), Math.min(height, Math.round(b))])
        .filter(([a, b]) => b > a)
        .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const out = [];
    for (const [a, b] of valid) {
        if (!out.length || a > out[out.length - 1][1]) out.push([a, b]);
        else out[out.length - 1][1] = Math.max(out[out.length - 1][1], b);
    }
    return out;
}

function writeRegions(widget, regions, node) {
    setWidgetValue(widget, JSON.stringify(regions), node);
}

function styleInput(el, modern) {
    el.style.width = "100%";
    el.style.boxSizing = "border-box";
    el.style.height = modern ? "32px" : "30px";
    el.style.borderRadius = modern ? "8px" : "6px";
    el.style.border = "1px solid rgba(255,255,255,0.16)";
    el.style.background = modern ? "rgba(255,255,255,0.055)" : "rgba(255,255,255,0.06)";
    el.style.color = "inherit";
    el.style.padding = "0 8px";
    el.style.fontSize = "12px";
    return el;
}

function fieldRow(labelText, control, modern) {
    const row = document.createElement("div");
    row.style.display = "grid";
    row.style.gridTemplateColumns = modern ? "96px minmax(0,1fr)" : "86px minmax(0,1fr)";
    row.style.gap = "8px";
    row.style.alignItems = "center";
    row.style.marginBottom = "7px";
    const label = document.createElement("div");
    label.textContent = labelText;
    label.style.fontSize = "11px";
    label.style.opacity = "0.88";
    label.style.whiteSpace = "normal";
    label.style.overflowWrap = "anywhere";
    row.append(label, control);
    return row;
}

function section(title, modern, open = true) {
    const d = document.createElement("details");
    d.open = open;
    d.style.border = "1px solid rgba(255,255,255,0.10)";
    d.style.borderRadius = modern ? "10px" : "8px";
    d.style.background = modern ? "rgba(255,255,255,0.025)" : "rgba(255,255,255,0.035)";
    d.style.overflow = "hidden";
    const s = document.createElement("summary");
    s.textContent = title;
    s.style.padding = modern ? "9px 11px" : "8px 10px";
    s.style.cursor = "pointer";
    s.style.fontSize = "12px";
    s.style.fontWeight = "700";
    s.style.whiteSpace = "normal";
    s.style.overflowWrap = "anywhere";
    const b = document.createElement("div");
    b.style.padding = "8px";
    d.append(s, b);
    return { details: d, body: b };
}

function buildEditor(node, modern) {
    const enableW = getWidget(node, "启用文字面板", "text_panel_enabled");
    const topW = getWidget(node, "选区上边界(px)", "selection_top_px");
    const bottomW = getWidget(node, "选区下边界(px)", "selection_bottom_px");
    const regionsW = getWidget(node, "截面列表", "regions_json");
    const bgModeW = getWidget(node, "面板背景", "panel_background");
    const bgColorW = getWidget(node, "背景颜色", "background_color");
    const textW = getWidget(node, "文字内容", "text");
    const textColorW = getWidget(node, "文字颜色", "text_color");
    const fontW = getWidget(node, "字体名称或路径", "font_name_or_path");
    const fontSizeW = getWidget(node, "字号", "font_size");
    const paddingW = getWidget(node, "内边距", "padding");
    const lineSpacingW = getWidget(node, "行距", "line_spacing");
    const hAlignW = getWidget(node, "水平对齐", "horizontal_align");
    const vAlignW = getWidget(node, "垂直对齐", "vertical_align");

    [enableW, topW, bottomW, regionsW, bgModeW, bgColorW, textW, textColorW, fontW, fontSizeW, paddingW, lineSpacingW, hAlignW, vAlignW].forEach(hideWidget);

    const root = document.createElement("div");
    root.dataset.hbeUi = modern ? "nodes2" : "classic";
    root.style.width = "100%";
    root.style.boxSizing = "border-box";
    root.style.padding = modern ? "8px 10px" : "8px";
    root.style.display = "flex";
    root.style.flexDirection = "column";
    root.style.gap = "8px";
    root.style.fontFamily = "inherit";
    root.style.color = "inherit";

    // 固定可视高度 + 内部滚动，不再要求用户手动拉高整个节点
    const viewport = document.createElement("div");
    viewport.style.maxHeight = modern ? "620px" : "560px";
    viewport.style.height = modern ? "620px" : "560px";
    viewport.style.overflowY = "auto";
    viewport.style.overflowX = "hidden";
    viewport.style.paddingRight = "4px";
    viewport.style.boxSizing = "border-box";
    viewport.style.scrollbarGutter = "stable";
    viewport.style.display = "flex";
    viewport.style.flexDirection = "column";
    viewport.style.gap = "8px";
    root.appendChild(viewport);

    const header = document.createElement("div");
    header.style.display = "flex";
    header.style.alignItems = "center";
    header.style.justifyContent = "space-between";
    header.style.gap = "8px";
    const title = document.createElement("div");
    title.textContent = "横向区域编辑";
    title.style.fontSize = modern ? "14px" : "13px";
    title.style.fontWeight = "700";
    const badge = document.createElement("div");
    badge.textContent = modern ? "Nodes 2.0" : "经典节点";
    badge.style.fontSize = "10px";
    badge.style.opacity = "0.72";
    header.append(title, badge);
    viewport.appendChild(header);

    const modeSec = section("操作模式", modern, true);
    viewport.appendChild(modeSec.details);
    const toggleRow = document.createElement("label");
    toggleRow.style.display = "flex";
    toggleRow.style.alignItems = "center";
    toggleRow.style.justifyContent = "space-between";
    toggleRow.style.gap = "8px";
    toggleRow.style.fontSize = "12px";
    toggleRow.style.whiteSpace = "normal";
    const toggleText = document.createElement("span");
    toggleText.textContent = "将截面替换为文字面板";
    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.checked = Boolean(enableW?.value);
    toggle.style.width = "18px";
    toggle.style.height = "18px";
    toggle.addEventListener("change", () => setWidgetValue(enableW, toggle.checked, node));
    toggleRow.append(toggleText, toggle);
    modeSec.body.appendChild(toggleRow);
    const modeHint = document.createElement("div");
    modeHint.style.fontSize = "11px";
    modeHint.style.opacity = "0.72";
    modeHint.style.marginTop = "6px";
    modeHint.style.whiteSpace = "normal";
    modeHint.style.overflowWrap = "anywhere";
    modeSec.body.appendChild(modeHint);

    const previewSec = section("预览与截面", modern, true);
    viewport.appendChild(previewSec.details);

    const buttonRow = document.createElement("div");
    buttonRow.style.display = "grid";
    buttonRow.style.gridTemplateColumns = "1fr 1fr";
    buttonRow.style.gap = "8px";
    buttonRow.style.marginBottom = "7px";
    function button(label) {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = label;
        b.style.minHeight = "32px";
        b.style.whiteSpace = "normal";
        b.style.lineHeight = "1.25";
        b.style.borderRadius = modern ? "8px" : "6px";
        b.style.border = "1px solid rgba(255,255,255,0.16)";
        b.style.background = "rgba(255,255,255,0.06)";
        b.style.color = "inherit";
        b.style.cursor = "pointer";
        b.style.fontSize = "11px";
        return b;
    }
    const syncBtn = button("从输入图像同步预览");
    const refreshBtn = button("刷新预览");
    buttonRow.append(syncBtn, refreshBtn);
    previewSec.body.appendChild(buttonRow);

    const sourceInfo = document.createElement("div");
    sourceInfo.style.fontSize = "11px";
    sourceInfo.style.opacity = "0.72";
    sourceInfo.style.whiteSpace = "normal";
    sourceInfo.style.overflowWrap = "anywhere";
    sourceInfo.style.marginBottom = "7px";
    previewSec.body.appendChild(sourceInfo);

    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 360;
    canvas.style.width = "100%";
    canvas.style.height = "auto";
    canvas.style.display = "block";
    canvas.style.border = "1px solid rgba(255,255,255,0.16)";
    canvas.style.borderRadius = modern ? "9px" : "6px";
    canvas.style.background = "repeating-conic-gradient(#292929 0 25%, #343434 0 50%) 0 / 16px 16px";
    canvas.style.cursor = "crosshair";
    canvas.style.touchAction = "none";
    previewSec.body.appendChild(canvas);

    const previewInfo = document.createElement("div");
    previewInfo.style.fontSize = "11px";
    previewInfo.style.opacity = "0.8";
    previewInfo.style.marginTop = "6px";
    previewInfo.style.whiteSpace = "normal";
    previewInfo.style.overflowWrap = "anywhere";
    previewSec.body.appendChild(previewInfo);

    const rangeGrid = document.createElement("div");
    rangeGrid.style.display = "grid";
    rangeGrid.style.gridTemplateColumns = "1fr 1fr";
    rangeGrid.style.gap = "8px";
    rangeGrid.style.marginTop = "8px";
    const topInput = styleInput(document.createElement("input"), modern);
    topInput.type = "number";
    topInput.min = "0";
    topInput.value = String(topW?.value ?? 0);
    const bottomInput = styleInput(document.createElement("input"), modern);
    bottomInput.type = "number";
    bottomInput.min = "1";
    bottomInput.value = String(bottomW?.value ?? 1);
    rangeGrid.append(fieldRow("上边界", topInput, modern), fieldRow("下边界", bottomInput, modern));
    previewSec.body.appendChild(rangeGrid);

    const regionActions = document.createElement("div");
    regionActions.style.display = "grid";
    regionActions.style.gridTemplateColumns = "1fr 1fr";
    regionActions.style.gap = "7px";
    regionActions.style.marginTop = "4px";
    const addBtn = button("添加当前截面");
    const updateBtn = button("更新选中截面");
    const removeBtn = button("移除选中截面");
    const clearBtn = button("清空全部截面");
    regionActions.append(addBtn, updateBtn, removeBtn, clearBtn);
    previewSec.body.appendChild(regionActions);

    const regionList = document.createElement("div");
    regionList.style.display = "flex";
    regionList.style.flexDirection = "column";
    regionList.style.gap = "5px";
    regionList.style.marginTop = "8px";
    previewSec.body.appendChild(regionList);

    const textSec = section("文字面板", modern, true);
    viewport.appendChild(textSec.details);
    const bgMode = styleInput(document.createElement("select"), modern);
    for (const v of ["纯色", "透明"]) {
        const o = document.createElement("option"); o.value = v; o.textContent = v; bgMode.appendChild(o);
    }
    bgMode.value = String(bgModeW?.value || "纯色");
    textSec.body.appendChild(fieldRow("面板背景", bgMode, modern));

    function colorControl(initial, fallback) {
        const wrap = document.createElement("div");
        wrap.style.display = "grid";
        wrap.style.gridTemplateColumns = "40px 1fr";
        wrap.style.gap = "8px";
        const picker = document.createElement("input");
        picker.type = "color";
        picker.value = /^#[0-9a-f]{6}$/i.test(String(initial || "")) ? String(initial) : fallback;
        picker.style.width = "38px"; picker.style.height = "30px"; picker.style.border = "0"; picker.style.padding = "0";
        const hex = styleInput(document.createElement("input"), modern);
        hex.value = String(initial || fallback).toUpperCase();
        wrap.append(picker, hex);
        return { wrap, picker, hex };
    }
    const bgColor = colorControl(bgColorW?.value, "#FFFFFF");
    const bgColorRow = fieldRow("背景颜色", bgColor.wrap, modern);
    textSec.body.appendChild(bgColorRow);
    const textColor = colorControl(textColorW?.value, "#000000");
    textSec.body.appendChild(fieldRow("文字颜色", textColor.wrap, modern));

    const textArea = document.createElement("textarea");
    textArea.value = String(textW?.value || "");
    textArea.style.width = "100%";
    textArea.style.minHeight = "100px";
    textArea.style.resize = "vertical";
    textArea.style.boxSizing = "border-box";
    textArea.style.borderRadius = modern ? "8px" : "6px";
    textArea.style.border = "1px solid rgba(255,255,255,0.16)";
    textArea.style.background = "rgba(255,255,255,0.055)";
    textArea.style.color = "inherit";
    textArea.style.padding = "8px";
    textArea.style.whiteSpace = "pre-wrap";
    textArea.style.overflowWrap = "anywhere";
    textSec.body.appendChild(fieldRow("文字内容", textArea, modern));

    const typographySec = section("排版", modern, false);
    viewport.appendChild(typographySec.details);
    const fontInput = styleInput(document.createElement("input"), modern);
    fontInput.value = String(fontW?.value || "SimHei");
    typographySec.body.appendChild(fieldRow("字体", fontInput, modern));
    function numberInput(value, min, max) {
        const el = styleInput(document.createElement("input"), modern);
        el.type = "number"; el.value = String(value); el.min = String(min); el.max = String(max); el.step = "1"; return el;
    }
    const fontSize = numberInput(fontSizeW?.value ?? 48, 1, 1024);
    const padding = numberInput(paddingW?.value ?? 24, 0, 2048);
    const spacing = numberInput(lineSpacingW?.value ?? 8, 0, 1024);
    typographySec.body.appendChild(fieldRow("字号", fontSize, modern));
    typographySec.body.appendChild(fieldRow("内边距", padding, modern));
    typographySec.body.appendChild(fieldRow("行距", spacing, modern));
    const hAlign = styleInput(document.createElement("select"), modern);
    ["居中", "左对齐", "右对齐"].forEach((v) => { const o=document.createElement("option"); o.value=v; o.textContent=v; hAlign.appendChild(o); });
    hAlign.value = String(hAlignW?.value || "居中");
    const vAlign = styleInput(document.createElement("select"), modern);
    ["居中", "顶部", "底部"].forEach((v) => { const o=document.createElement("option"); o.value=v; o.textContent=v; vAlign.appendChild(o); });
    vAlign.value = String(vAlignW?.value || "居中");
    typographySec.body.appendChild(fieldRow("水平对齐", hAlign, modern));
    typographySec.body.appendChild(fieldRow("垂直对齐", vAlign, modern));

    const state = {
        img: null,
        dragging: false,
        anchorY: 0,
        displayRect: { x: 0, y: 0, w: 1, h: 1 },
        selectedRegionIndex: -1,
        filename: null,
    };

    function activeRange() {
        const h = state.img?.naturalHeight || 16384;
        let a = Math.round(Number(topW?.value ?? topInput.value ?? 0));
        let b = Math.round(Number(bottomW?.value ?? bottomInput.value ?? 1));
        a = Math.max(0, Math.min(h - 1, a));
        b = Math.max(a + 1, Math.min(h, b));
        return [a, b];
    }

    function savedRegions() {
        const h = state.img?.naturalHeight || Infinity;
        return normalizeRegions(parseRegions(regionsW?.value), h);
    }

    function renderRegionList() {
        regionList.innerHTML = "";
        const regions = savedRegions();
        if (!regions.length) {
            const empty = document.createElement("div");
            empty.textContent = "尚未保存多个截面；执行时会使用当前蓝色选区。";
            empty.style.fontSize = "11px";
            empty.style.opacity = "0.68";
            empty.style.whiteSpace = "normal";
            regionList.appendChild(empty);
            return;
        }
        regions.forEach(([a, b], idx) => {
            const item = document.createElement("button");
            item.type = "button";
            item.textContent = `截面 ${a}–${b}px（${b-a}px）`;
            item.style.textAlign = "left";
            item.style.whiteSpace = "normal";
            item.style.overflowWrap = "anywhere";
            item.style.padding = "6px 8px";
            item.style.borderRadius = "6px";
            item.style.border = idx === state.selectedRegionIndex ? "1px solid rgba(100,190,255,.95)" : "1px solid rgba(255,255,255,.12)";
            item.style.background = idx === state.selectedRegionIndex ? "rgba(80,150,240,.16)" : "rgba(255,255,255,.035)";
            item.style.color = "inherit";
            item.style.cursor = "pointer";
            item.addEventListener("click", () => {
                state.selectedRegionIndex = idx;
                setWidgetValue(topW, a, node);
                setWidgetValue(bottomW, b, node);
                topInput.value = String(a); bottomInput.value = String(b);
                renderRegionList(); draw();
            });
            regionList.appendChild(item);
        });
    }

    function dynamicUI() {
        const enabled = Boolean(enableW?.value);
        toggle.checked = enabled;
        textSec.details.style.display = enabled ? "block" : "none";
        typographySec.details.style.display = enabled ? "block" : "none";
        modeHint.textContent = enabled
            ? "所有已保存截面都会替换为同一套文字面板；文字过高时分别自动扩展。"
            : "所有已保存截面都会被删除，然后将剩余图像按原顺序拼接。";
        bgColorRow.style.display = String(bgModeW?.value || "纯色") === "透明" ? "none" : "grid";
    }

    function refreshSource() {
        const src = getConnectedLoadImage(node);
        sourceInfo.textContent = src ? `预览来源：${src.title} → ${src.filename}` : "未检测到可直接读取文件名的“加载图像”上游节点。";
        return src;
    }

    function draw() {
        const ctx = canvas.getContext("2d");
        const cssW = Math.max(320, Math.floor(previewSec.body.getBoundingClientRect().width || 400));
        const dpr = Math.max(1, window.devicePixelRatio || 1);
        let cssH = 220;
        if (state.img?.naturalWidth && state.img?.naturalHeight) cssH = Math.max(170, Math.min(430, cssW * state.img.naturalHeight / state.img.naturalWidth));
        canvas.style.height = `${cssH}px`;
        canvas.width = Math.floor(cssW * dpr); canvas.height = Math.floor(cssH * dpr);
        ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,cssW,cssH);
        if (!state.img?.naturalWidth) {
            ctx.fillStyle = "rgba(255,255,255,.72)"; ctx.font = "13px sans-serif"; ctx.textAlign="center"; ctx.textBaseline="middle";
            ctx.fillText("请先同步输入图像预览", cssW/2, cssH/2);
            previewInfo.textContent = "未加载预览图像";
            return;
        }
        const scale = Math.min(cssW/state.img.naturalWidth, cssH/state.img.naturalHeight);
        const dw = state.img.naturalWidth*scale, dh = state.img.naturalHeight*scale, dx=(cssW-dw)/2, dy=(cssH-dh)/2;
        state.displayRect = {x:dx,y:dy,w:dw,h:dh}; ctx.drawImage(state.img,dx,dy,dw,dh);

        for (const [a,b] of savedRegions()) {
            const y1=dy+a/state.img.naturalHeight*dh, y2=dy+b/state.img.naturalHeight*dh;
            ctx.fillStyle="rgba(255,176,64,.20)"; ctx.fillRect(dx,y1,dw,Math.max(1,y2-y1));
            ctx.strokeStyle="rgba(255,190,80,.9)"; ctx.lineWidth=1.5; ctx.strokeRect(dx+1,y1,Math.max(1,dw-2),Math.max(1,y2-y1));
        }
        const [a,b]=activeRange(); const y1=dy+a/state.img.naturalHeight*dh, y2=dy+b/state.img.naturalHeight*dh;
        ctx.fillStyle="rgba(70,160,255,.18)"; ctx.fillRect(dx,y1,dw,Math.max(1,y2-y1));
        ctx.strokeStyle="rgba(100,190,255,.98)"; ctx.lineWidth=2; ctx.strokeRect(dx+1,y1,Math.max(1,dw-2),Math.max(1,y2-y1));
        previewInfo.textContent = `图像 ${state.img.naturalWidth}×${state.img.naturalHeight}；当前选区 ${a}–${b}px；已保存 ${savedRegions().length} 个截面。`;
    }

    function clientYToImageY(clientY) {
        if (!state.img?.naturalHeight) return 0;
        const r=canvas.getBoundingClientRect(), cy=clientY-r.top, d=state.displayRect;
        const clamped=Math.max(d.y,Math.min(d.y+d.h,cy));
        return Math.round(((clamped-d.y)/Math.max(1,d.h))*state.img.naturalHeight);
    }

    function setActive(a,b) {
        if (!state.img?.naturalHeight) return;
        const h=state.img.naturalHeight;
        let y1=Math.round(Math.min(a,b)), y2=Math.round(Math.max(a,b));
        y1=Math.max(0,Math.min(h-1,y1)); y2=Math.max(y1+1,Math.min(h,y2));
        setWidgetValue(topW,y1,node); setWidgetValue(bottomW,y2,node);
        topInput.value=String(y1); bottomInput.value=String(y2); draw();
    }

    function loadPreview(force=true) {
        const src=refreshSource();
        if (!src?.filename) { previewInfo.textContent="只有上游为“加载图像”时才能直接同步预览；后端 IMAGE 输入仍可正常执行。"; return; }
        if (!force && state.filename===src.filename && state.img) { draw(); return; }
        state.filename=src.filename;
        const img=new Image();
        img.onload=()=>{
            state.img=img;
            const [a,b]=activeRange();
            if ((Number(topW?.value)||0)===0 && (Number(bottomW?.value)||1)<=1) setActive(Math.floor(img.naturalHeight/3),Math.ceil(img.naturalHeight*2/3));
            else setActive(a,b);
            renderRegionList(); draw();
        };
        img.onerror=()=>{ state.img=null; previewInfo.textContent="预览读取失败。"; draw(); };
        img.src=`${makeViewUrl(src.filename)}&rand=${Date.now()}`;
    }

    canvas.addEventListener("pointerdown",(e)=>{ if(!state.img)return; state.dragging=true; state.anchorY=clientYToImageY(e.clientY); canvas.setPointerCapture?.(e.pointerId); setActive(state.anchorY,state.anchorY+1); e.preventDefault(); });
    canvas.addEventListener("pointermove",(e)=>{ if(!state.dragging)return; setActive(state.anchorY,clientYToImageY(e.clientY)); e.preventDefault(); });
    const end=(e)=>{ if(!state.dragging)return; state.dragging=false; try{canvas.releasePointerCapture?.(e.pointerId)}catch(_){} e.preventDefault(); };
    canvas.addEventListener("pointerup",end); canvas.addEventListener("pointercancel",end);

    syncBtn.addEventListener("click",()=>loadPreview(true)); refreshBtn.addEventListener("click",()=>loadPreview(true));
    topInput.addEventListener("change",()=>setActive(Number(topInput.value),Number(bottomInput.value)));
    bottomInput.addEventListener("change",()=>setActive(Number(topInput.value),Number(bottomInput.value)));

    addBtn.addEventListener("click",()=>{
        const h=state.img?.naturalHeight||Infinity;
        const next=normalizeRegions([...savedRegions(),activeRange()],h);
        writeRegions(regionsW,next,node); state.selectedRegionIndex=Math.max(0,next.findIndex(([a,b])=>a<=activeRange()[0]&&b>=activeRange()[1])); renderRegionList(); draw();
    });
    updateBtn.addEventListener("click",()=>{
        const regs=savedRegions(); if(state.selectedRegionIndex<0||state.selectedRegionIndex>=regs.length)return;
        regs[state.selectedRegionIndex]=activeRange(); const next=normalizeRegions(regs,state.img?.naturalHeight||Infinity);
        writeRegions(regionsW,next,node); state.selectedRegionIndex=Math.min(state.selectedRegionIndex,next.length-1); renderRegionList(); draw();
    });
    removeBtn.addEventListener("click",()=>{
        const regs=savedRegions(); if(state.selectedRegionIndex<0||state.selectedRegionIndex>=regs.length)return;
        regs.splice(state.selectedRegionIndex,1); writeRegions(regionsW,regs,node); state.selectedRegionIndex=Math.min(state.selectedRegionIndex,regs.length-1); renderRegionList(); draw();
    });
    clearBtn.addEventListener("click",()=>{ writeRegions(regionsW,[],node); state.selectedRegionIndex=-1; renderRegionList(); draw(); });

    bgMode.addEventListener("change",()=>setWidgetValue(bgModeW,bgMode.value,node));
    function bindColor(comp, widget) {
        comp.picker.addEventListener("input",()=>{comp.hex.value=comp.picker.value.toUpperCase();setWidgetValue(widget,comp.hex.value,node)});
        comp.hex.addEventListener("change",()=>{let v=comp.hex.value.trim().toUpperCase();if(!v.startsWith("#"))v="#"+v;if(/^#[0-9A-F]{6}$/.test(v)){comp.hex.value=v;comp.picker.value=v;setWidgetValue(widget,v,node)}});
    }
    bindColor(bgColor,bgColorW); bindColor(textColor,textColorW);
    textArea.addEventListener("input",()=>setWidgetValue(textW,textArea.value,node));
    fontInput.addEventListener("change",()=>setWidgetValue(fontW,fontInput.value,node));
    fontSize.addEventListener("change",()=>setWidgetValue(fontSizeW,Number(fontSize.value||48),node));
    padding.addEventListener("change",()=>setWidgetValue(paddingW,Number(padding.value||24),node));
    spacing.addEventListener("change",()=>setWidgetValue(lineSpacingW,Number(spacing.value||8),node));
    hAlign.addEventListener("change",()=>setWidgetValue(hAlignW,hAlign.value,node));
    vAlign.addEventListener("change",()=>setWidgetValue(vAlignW,vAlign.value,node));

    bindWidgetSync(enableW,dynamicUI);
    bindWidgetSync(bgModeW,()=>{bgMode.value=String(bgModeW?.value||"纯色");dynamicUI()});
    bindWidgetSync(regionsW,()=>{renderRegionList();draw()});
    bindWidgetSync(topW,()=>{topInput.value=String(topW?.value??0);draw()});
    bindWidgetSync(bottomW,()=>{bottomInput.value=String(bottomW?.value??1);draw()});

    dynamicUI(); renderRegionList(); refreshSource();
    const ro=new ResizeObserver(()=>draw()); ro.observe(root);
    node._hbeCleanup=()=>ro.disconnect();
    node._hbeReload=()=>{dynamicUI();renderRegionList();refreshSource();loadPreview(false)};
    requestAnimationFrame(()=>node._hbeReload?.());
    return root;
}

function mountEditor(node) {
    if (node._hbeMounted) return;
    node._hbeMounted = true;
    const modern = isNodes2Enabled();
    const root = buildEditor(node, modern);
    const fixedHeight = modern ? 640 : 580;
    const widget = node.addDOMWidget(
        modern ? "horizontal_band_editor_nodes2" : "horizontal_band_editor_classic",
        "custom",
        root,
        {
            serialize: false,
            hideOnZoom: false,
            getHeight: () => fixedHeight,
            getMinHeight: () => fixedHeight,
            getMaxHeight: () => fixedHeight,
            margin: modern ? 6 : 8,
        }
    );
    node._hbeDomWidget = widget;
    requestAnimationFrame(() => {
        const minW = modern ? 470 : 440;
        const minH = modern ? 730 : 680;
        node.setSize?.([Math.max(node.size?.[0] || minW, minW), Math.max(node.size?.[1] || minH, minH)]);
    });
}

app.registerExtension({
    name: "OpenAI.HorizontalBandEditor",
    async nodeCreated(node) {
        if (node?.comfyClass !== NODE_NAME && node?.type !== NODE_NAME) return;
        mountEditor(node);
    },
    async afterConfigureGraph() {
        for (const node of app.graph?._nodes || []) {
            if (node?.comfyClass === NODE_NAME || node?.type === NODE_NAME) node._hbeReload?.();
        }
    },
});
