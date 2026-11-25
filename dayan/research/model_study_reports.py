"""Research reports derived from the same verified model-study trials.

Figures never create predictions, fill missing trials, or score an unexamined
holdout. This is a descriptive evidence report, not an automatic causal review.
"""
from collections import defaultdict
from copy import deepcopy
from datetime import datetime,timezone
import csv
import hashlib
import json
import math
from pathlib import Path
import re
from zipfile import ZipFile, ZIP_DEFLATED

from ..collection.storage import atomic_json, file_lock, read_json
from ..solvers.codec import digest
from . import model_studies as studies
from .model_diagnostics import load_diagnostics


ROLES={'training':'训练','validation':'验证','holdout':'留出'}
COLORS={'training':'#147d92','validation':'#9063b0','holdout':'#c56b28'}
CONCLUSIONS={
    'passed_declared_checks':'通过本协议声明的有限检查',
    'passed_declared_checks_with_reused_holdout':'通过声明检查 但留出结果此前已被使用',
    'failed_predeclared_tolerance':'未通过事前误差阈值',
    'failed_holdout_execution':'留出求值执行失败',
    'failed_predeclared_diagnostics':'未通过事前数值诊断',
    'diagnostic_protocol_invalidated':'诊断协议无法按原计划执行',
    'all_training_candidates_failed':'全部训练候选执行失败',
    'all_validation_candidates_failed':'全部验证候选执行失败',
    'evaluated_without_full_acceptance_thresholds':'求值已完成 但未声明完整验收阈值'}


def _actual_parameter_context(result_run,trials,selected):
    if result_run:
        actual=result_run['manifest']['actual']
        return {'values':deepcopy(actual['effective_parameters']),
                'basis':'所选结果运行 '+result_run['run_id']+' 的实际开始参数'}
    if selected:
        trial=next((item for item in reversed(trials)
            if item['candidate']==selected['candidate'] and item['status']=='evaluated'),None)
        if trial:
            actual=trial['receipt']['actual']
            return {'values':deepcopy(actual['effective_parameters']),
                    'basis':'所选候选的实际'+ROLES[trial['role']]+'求值 '+trial['receipt']['run_id']}
    return {'values':{},'basis':'尚未取得所选候选的实际执行参数；默认值不是本次有效值'}


def _runtime_text_inputs(evaluation):
    """Expose small text inputs already frozen in the executed study.

    This is a source-linked presentation of existing inputs, not a retroactive
    addition of evidence to the approved model or an assertion of causal use.
    Large record tables remain in the replication package, not Word paragraphs.
    """
    from ..structured_inputs import prepare_structured
    result=[]
    for frozen in evaluation['input_evidence']:
        contract=frozen.get('contract',{})
        if (not frozen.get('port') or contract.get('kind')!='records'
                or frozen.get('records_used')!=1 or not contract.get('fields')
                or any(spec['type']!='string' for spec in contract['fields'].values())):
            continue
        inputs,evidence=prepare_structured([frozen['binding']],{frozen['port']:contract})
        current,=evidence
        for key in ('dataset_id','sha256','data_sha256','input_sha256','binding','columns','records_used'):
            if current[key]!=frozen[key]:
                raise ValueError('科研文字输入与实际研究版本不一致：'+key)
        port=inputs[frozen['port']]
        fields={name:{'text':values[0],
                       'source_field':frozen['columns'][name].get('pointer',frozen['columns'][name].get('field'))}
                for name,values in port['columns'].items() if values[0] is not None}
        result.append({'port':frozen['port'],'dataset_id':frozen['dataset_id'],
            'source':frozen['source'],'sha256':frozen['sha256'],'data_sha256':frozen['data_sha256'],
            'path':frozen['path'],'source_row_index':port['source_row_indices'][0],
            'input_sha256':frozen['input_sha256'],'fields':fields})
    return result


def evidence(study_id):
    loaded=studies.load_study(study_id)
    protocol,state=loaded['protocol'],loaded['state']
    if state['status'] not in ('complete','failed'):
        raise ValueError('研究尚未完成或完整性失效，不能生成最终科研报告')
    folder=studies.directory(study_id)
    trials=[]
    for row in state['trials']:
        path=folder/row['directory']
        receipt=studies._verified_trial(path)
        trials.append({**deepcopy(row),'receipt':receipt,
            **({'fit':read_json(path/'fit.json'),'manifest':read_json(path/'manifest.json')}
               if receipt['status']=='evaluated' else {})})
    diagnostics=(load_diagnostics(protocol['evaluation'],state['selection']['parameters'],
        protocol['diagnostics'],protocol['seeds'],directory=folder/'diagnostics')
        if state.get('diagnostics') else None)
    selected=state.get('selection')
    from .model_study_runs import verify_selected_run
    result_run=verify_selected_run(loaded)
    points=[]
    if selected:
        for trial in trials:
            if trial['candidate']==selected['candidate'] and trial['status']=='evaluated':
                points.extend({**deepcopy(point),'role':trial['role'],'seed':trial['seed'],
                    'candidate':trial['candidate'],'trial_directory':trial['directory']}
                    for point in trial['fit']['points'])
    result={'study_id':study_id,'protocol':protocol,'state':state,'summary':studies.summary(loaded),
            'trials':trials,'selected_predictions':points,'diagnostics':diagnostics,'result_run':result_run,
            'interpretation_limits':['原始数据质量与领域代表性不由拟合误差证明',
                '重复的样本标准差和标准误不是参数置信区间或现实预测区间',
                '参数响应是固定其他参数的有限扫描 消融不能自动证明现实政策因果',
                '数值诊断没有评分留出目标 同一seed不证明跨步长的共同噪声路径',
                '有限网格没有证明参数可识别或全局最优']}
    source=protocol.get('baseline',{}).get('source_evidence')
    if source:
        from .source_evidence import verify_evidence
        result['source_evidence']=verify_evidence(source,targets=protocol['evaluation']['targets'])
    result['evidence_sha256']=digest(result)
    # Presentation is derived from the already sealed actual parameters/input
    # bindings. Keep the scientific evidence identity stable across formatting
    # upgrades; renderer and published-file hashes version these new fields.
    result['presentation']={
        'actual_parameters':_actual_parameter_context(result_run,trials,selected),
        'runtime_text_inputs':_runtime_text_inputs(protocol['evaluation']),
        'execution_method':_archived_execution_method(result),
        'analysis':_descriptive_analysis(result)}
    return result


def _archived_execution_method(facts):
    """Use the actual run's source-backed method, not an Agent's prose summary."""
    if facts.get('result_run'):
        manifest=facts['result_run']['manifest'];origin=facts['result_run']['run_id']
    else:
        row=next((r for r in facts['trials'] if r['status']=='evaluated'),None)
        if row:manifest=row['manifest'];origin=row['receipt']['run_id']
        else:
            baseline=facts['protocol'].get('baseline',{})
            manifest=baseline.get('manifest',{});origin=baseline.get('run_id')
    method=manifest.get('model_method') or {}
    if method.get('source')!='archived_dsl':return None
    return {'origin_run_id':origin,'source':method['source'],
            'integration':deepcopy(method.get('integration',[])),
            'integration_equations':[deepcopy(row) for row in method.get('equations',[]) if row['group']=='RK4 积分']}


def _descriptive_analysis(facts):
    """Describe actual saved trajectories, residuals and comparisons, without inference.

    Raw residual summaries use every executed replicate. They never replace the
    predeclared per-run loss, invent an unscored holdout, or construct intervals.
    This presentation layer intentionally does not change scientific evidence ID.
    """
    outputs=facts['protocol']['evaluation']['model']['observables']
    result={'version':'dayan-saved-study-description-v1','trajectories':[],
            'residuals':[],'diagnostic_comparisons':[]}
    actual=facts.get('result_run')
    if actual:
        rows=actual['observations']
        for name,spec in outputs.items():
            values=[row[name] for row in rows]
            change=values[-1]-values[0]
            result['trajectories'].append({'observable':name,'unit':spec['unit'],
                'run_id':actual['run_id'],'points':len(rows),'start_time':rows[0]['sim_t'],
                'end_time':rows[-1]['sim_t'],'start':values[0],'end':values[-1],
                'change':change,'relative_change':change/abs(values[0]) if values[0] else None,
                'minimum':min(values),'maximum':max(values),
                'scope':'所选参数的一个实际完整结果运行；不替代多种子均值'})
    points=facts['selected_predictions']
    for name in sorted({row['observable'] for row in points}):
        for role in ROLES:
            rows=[row for row in points if row['observable']==name and row['role']==role]
            if not rows:continue
            errors=[row['residual_predicted_minus_observed'] for row in rows]
            scale=max(abs(value) for value in errors)
            maximum=max(rows,key=lambda row:abs(row['residual_predicted_minus_observed']))
            identities={(row['binding_id'],digest(row.get('series',{})),row['time'],
                         row.get('provenance',{}).get('content_cell')) for row in rows}
            result['residuals'].append({'observable':name,'role':role,'unit':rows[0]['unit'],
                'observation_count':len(identities),'actual_point_count':len(rows),
                'seeds':list(dict.fromkeys(row['seed'] for row in rows)),
                'start_time':min(row['time'] for row in rows),'end_time':max(row['time'] for row in rows),
                'mean_error':math.fsum(value/len(errors) for value in errors),
                'mae':math.fsum(abs(value)/len(errors) for value in errors),
                'rmse':scale*math.sqrt(math.fsum((value/scale)**2 for value in errors)/len(errors)) if scale else 0.,
                'max_abs_error':scale,'max_error_time':maximum['time'],'max_error_seed':maximum['seed'],
                'positive':sum(value>0 for value in errors),'negative':sum(value<0 for value in errors),
                'zero':sum(value==0 for value in errors),
                'scope':'全部实际重复的逐点残差描述；符号不等于显著性检验，时间相关点不是独立样本'})
    for report in (facts.get('diagnostics') or {}).get('reports',[]):
        for difference in report['differences_from_baseline']:
            profile=next(p for p in report['profiles'] if p['label']==difference['label'])
            baseline=report['profiles'][0]
            for name,spec in report['specification']['outputs'].items():
                rows=difference['points']
                maximum=max(rows,key=lambda row:abs(row['metrics'][name]['mean']))
                result['diagnostic_comparisons'].append({'id':report['id'],'kind':report['kind'],
                    'observable':name,'unit':spec['unit'],'variant':profile['label'],
                    'parameters':profile['parameters'],'dt':profile['dt'],
                    'end_time':rows[-1]['sim_t'],'baseline_end_mean':baseline['points'][-1]['metrics'][name]['mean'],
                    'variant_end_mean':profile['points'][-1]['metrics'][name]['mean'],
                    'end_mean_difference':rows[-1]['metrics'][name]['mean'],
                    'max_abs_mean_difference':abs(maximum['metrics'][name]['mean']),
                    'max_mean_difference_time':maximum['sim_t'],
                    'replicates':len(profile['points'][-1]['metrics'][name]['values'])})
    return result


def _csv(path,rows,fields):
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({key:json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else value
                             for key,value in row.items()})


def _figures(facts,folder):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    from ..fonts import font_family
    figures=[]
    def save(fig,title,caption,kind,rows,*,observable=None,diagnostic_id=None):
        name=f'figure_{len(figures)+1:03d}.png'
        fig.savefig(folder/name,dpi=170,facecolor='white',bbox_inches='tight',pad_inches=.12)
        plt.close(fig)
        figures.append({'file':name,'title':title,'caption':caption,'kind':kind,
                        'data':rows,'data_sha256':digest(rows),
                        **({'observable':observable} if observable else {}),
                        **({'diagnostic_id':diagnostic_id} if diagnostic_id else {})})
    outputs=facts['protocol']['evaluation']['model']['observables']
    output_label=lambda name:outputs[name].get('label',name)
    with matplotlib.rc_context({'font.family':font_family(),'axes.spines.top':False,
            'axes.spines.right':False,'font.size':10,'axes.grid':True,'grid.alpha':.15}):
        points=facts['selected_predictions']
        for observable in sorted({row['observable'] for row in points}):
            rows=[row for row in points if row['observable']==observable]
            grouped=defaultdict(list)
            for row in rows:grouped[(row['role'],row['time'])].append(row)
            values=[]
            for (role,time),items in grouped.items():
                observed={item['value'] for item in items}
                if len(observed)!=1:raise ValueError('同一观测在实际重复中不一致')
                samples=[item['predicted'] for item in items]
                mean=math.fsum(samples)/len(samples)
                sd=(math.sqrt(math.fsum((x-mean)**2 for x in samples)/(len(samples)-1)) if len(samples)>1 else None)
                values.append({'role':role,'time':time,'observed':observed.pop(),'predicted_mean':mean,
                    'predicted_sample_sd':sd,'actual_replicates':len(samples)})
            values.sort(key=lambda row:row['time'])
            unit=rows[0]['unit']
            fig,ax=plt.subplots(figsize=(7.2,3.2),layout='constrained')
            for role in ROLES:
                group=[row for row in values if row['role']==role]
                if not group:continue
                x=[row['time'] for row in group]
                ax.plot(x,[row['observed'] for row in group],'o',color=COLORS[role],label=ROLES[role]+'观测')
                ax.plot(x,[row['predicted_mean'] for row in group],'-x',color=COLORS[role],label=ROLES[role]+'模型均值')
                if all(row['predicted_sample_sd'] is not None for row in group):
                    ax.fill_between(x,[r['predicted_mean']-r['predicted_sample_sd'] for r in group],
                        [r['predicted_mean']+r['predicted_sample_sd'] for r in group],color=COLORS[role],alpha=.12)
            ax.set(xlabel='模型时间',ylabel=f'{observable}（{unit}）');ax.legend(fontsize=8,ncol=2)
            save(fig,f'{output_label(observable)} 实测与模型对照',
                '只绘制所选参数已经求值的分区。阴影如存在为实际重复均值上下一个样本标准差；单次运行不画区间。优化损失按逐次运行计算，不是均值曲线的误差。',
                'observed_and_predicted',values,observable=observable)
            fig,axes=plt.subplots(1,2,figsize=(7.2,3.15),layout='constrained')
            for role in ROLES:
                group=[row for row in rows if row['role']==role]
                if not group:continue
                residuals=sorted(row['residual_predicted_minus_observed'] for row in group)
                axes[0].scatter([row['time'] for row in group],
                    [row['residual_predicted_minus_observed'] for row in group],s=18,alpha=.7,color=COLORS[role],label=ROLES[role])
                axes[1].step(residuals,[(i+1)/len(residuals) for i in range(len(residuals))],where='post',marker='o',markersize=3,color=COLORS[role])
            axes[0].axhline(0,c='#777777',lw=.8);axes[0].legend(fontsize=8)
            axes[0].set(xlabel='模型时间',ylabel=f'预测减观测（{unit}）')
            axes[1].set(xlabel=f'残差（{unit}）',ylabel='实际残差经验累计比例',ylim=(0,1.05))
            save(fig,f'{output_label(observable)} 残差时序与分布',
                '包含每个已执行种子的残差，没有平滑或生成额外样本。时间相关的残差不自动构成独立抽样。',
                'residuals',rows,observable=observable)
        candidates=[row for row in facts['trials'] if row['status']=='evaluated' and row['role']!='holdout']
        result=facts.get('result_run')
        if result:
            outputs=facts['protocol']['evaluation']['model']['observables']
            # Each output keeps its own unit/axis; no unrelated quantities are
            # silently placed on a shared physical scale.
            for name in outputs:
                rows=[{'sim_t':row['sim_t'],'value':row[name]} for row in result['observations']]
                fig,ax=plt.subplots(figsize=(7.2,3.1),layout='constrained')
                ax.plot([r['sim_t'] for r in rows],[r['value'] for r in rows],color='#147d92')
                ax.set(xlabel='实际模型时间',ylabel=name+'（'+outputs[name]['unit']+'）')
                save(fig,output_label(name)+' 所选模型实际完整轨迹','同一结果运行 '+result['run_id']+'；'+result['scope'],
                     'actual_selected_trajectory',rows,observable=name)
        if candidates:
            fig,ax=plt.subplots(figsize=(7.2,3.1),layout='constrained')
            for role in ('training','validation'):
                rows=[row for row in candidates if row['role']==role]
                ax.scatter([row['candidate'] for row in rows],[row['loss'] for row in rows],color=COLORS[role],label=ROLES[role],alpha=.7)
            ax.set(xlabel='固定网格的候选编号',ylabel='逐次实际运行的加权标准化均方误差');ax.legend(fontsize=8)
            ids=sorted({row['candidate'] for row in candidates})
            if len(ids)<=12:ax.set_xticks(ids)
            save(fig,'训练搜索与验证短名单','全部成功求值逐点显示；失败候选另列，不设为零或从统计中冒充成功。候选编号不是连续参数轴。',
                'candidate_losses',[{k:row[k] for k in ('role','candidate','seed','loss')} for row in candidates])
        for report in (facts.get('diagnostics') or {}).get('reports',[]):
            for observable,output in report['specification']['outputs'].items():
                fig,axes=plt.subplots(2,1,figsize=(7.2,4.5),layout='constrained',sharex=True)
                labels={p['label']:(f"dt = {p['dt']:g}" if report['kind']=='time_refinement' else
                    '；'.join(name+' = '+(f'{value:g}' if type(value) in (int,float) else str(value))
                             for name,value in p['parameters'].items())) for p in report['profiles']}
                colors={p['label']:f'C{i%10}' for i,p in enumerate(report['profiles'])}
                baseline=report['profiles'][0]['label']
                labels[baseline]='基准 '+labels[baseline]
                for profile in report['profiles']:
                    axes[0].plot([p['sim_t'] for p in profile['points']],
                        [p['metrics'][observable]['mean'] for p in profile['points']],
                        label=labels[profile['label']],color=colors[profile['label']])
                for profile in report['differences_from_baseline']:
                    axes[1].plot([p['sim_t'] for p in profile['points']],
                        [p['metrics'][observable]['mean'] for p in profile['points']],
                        label=labels[profile['label']],color=colors[profile['label']])
                axes[0].set(ylabel=f'{observable}（{output["unit"]}）');axes[0].legend(fontsize=8,ncol=3)
                axes[1].set(xlabel='相同物理模型时间',ylabel='相对基准的均值差');axes[1].axhline(0,c='#777777',lw=.7)
                axes[1].legend(fontsize=8,ncol=3)
                titles={'time_refinement':'时间分辨率检验','parameter_sweep':'参数响应比较','ablation':'机制消融比较'}
                save(fig,output_label(observable)+' '+titles[report['kind']],report['scope']+'。诊断编号 '+report['id']+'。',
                    report['kind'],{'profiles':report['profiles'],'differences':report['differences_from_baseline']},
                    observable=observable,diagnostic_id=report['id'])
    return figures


def _document(facts,figures,folder):
    from docx import Document
    from docx.shared import Inches,Pt,RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    protocol,state=facts['protocol'],facts['state']
    evaluation=protocol['evaluation'];model=evaluation['model'];definition=model['definition']
    doc=Document();section=doc.sections[0]
    section.page_width=Inches(8.5);section.page_height=Inches(11)
    section.top_margin=section.bottom_margin=Inches(.7)
    section.left_margin=section.right_margin=Inches(.8)
    for name in ('Normal','Title','Heading 1','Heading 2','Caption'):
        style=doc.styles[name];style.font.name='Noto Sans CJK SC';style.font.color.rgb=RGBColor(0,0,0)
        style.font.bold=name in ('Title','Heading 1','Heading 2')
        style.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'),'Noto Sans CJK SC')
        borders=OxmlElement('w:pBdr');bottom=OxmlElement('w:bottom');bottom.set(qn('w:val'),'nil');borders.append(bottom)
        style.element.get_or_add_pPr().append(borders)
    doc.styles['Normal'].font.size=Pt(11)
    doc.styles['Normal'].paragraph_format.space_after=Pt(6)
    doc.styles['Normal'].paragraph_format.line_spacing=1.18
    doc.styles['Title'].font.size=Pt(23)
    doc.styles['Heading 1'].font.size=Pt(15)
    doc.styles['Caption'].font.size=Pt(10)
    footer=section.footer.paragraphs[0];footer.alignment=1
    footer.add_run('DAYAN 研究报告  ')
    page=OxmlElement('w:fldSimple');page.set(qn('w:instr'),'PAGE');footer._p.append(page)
    for run in footer.runs:run.font.size=Pt(9);run.font.color.rgb=RGBColor(0,0,0)
    md=[]
    def paragraph(text):
        p=doc.add_paragraph(str(text));md.append(str(text)+'\n');return p
    def heading(text):doc.add_heading(text,level=1);md.append('## '+text+'\n')
    def number(value):return f'{value:.10g}' if type(value) in (int,float) else '未提供' if value is None else str(value)
    def pairs(values):return '；'.join(name+' = '+number(value) for name,value in values.items())
    def numeric_table(headers,rows,widths):
        table=doc.add_table(rows=0,cols=len(headers));table.autofit=False
        for column,width in zip(table.columns,widths):column.width=Inches(width)
        borders=OxmlElement('w:tblBorders')
        for edge in ('top','left','bottom','right','insideH','insideV'):
            border=OxmlElement('w:'+edge);border.set(qn('w:val'),'single')
            border.set(qn('w:sz'),'4');border.set(qn('w:color'),'D9D9D9');borders.append(border)
        table._tbl.tblPr.append(borders)
        for index,values in enumerate([headers,*rows]):
            row=table.add_row();props=row._tr.get_or_add_trPr();props.append(OxmlElement('w:cantSplit'))
            if index==0:props.append(OxmlElement('w:tblHeader'))
            for cell,text,width in zip(row.cells,values,widths):
                cell.width=Inches(width);cell.vertical_alignment=1
                p=cell.paragraphs[0];p.paragraph_format.space_after=Pt(3);p.paragraph_format.space_before=Pt(3)
                p.paragraph_format.line_spacing=1.08
                run=p.add_run(str(text));run.font.size=Pt(10);run.bold=index==0
                if index==0:
                    shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'E8EEF3');cell._tc.get_or_add_tcPr().append(shade)
        escape=lambda text:str(text).replace('|','\\|').replace('\n','<br>')
        md.extend(['| '+' | '.join(map(escape,headers))+' |',
                   '| '+' | '.join('---' for _ in headers)+' |',
                   *['| '+' | '.join(map(escape,row))+' |' for row in rows],''])
    def expression(text):
        # Stored expressions remain verbatim executable notation. Program source
        # is also included in the replication package; no invented derivation.
        p=doc.add_paragraph();math_node=OxmlElement('m:oMath')
        def math_run(parent,value):
            run=OxmlElement('m:r');node=OxmlElement('m:t');node.text=value
            node.set('{http://www.w3.org/XML/1998/namespace}space','preserve');run.append(node);parent.append(run)
        # Unicode subscript glyphs inside one m:t overlap in LibreOffice's math
        # layout. Encode their actual indices as editable OMML, preserving meaning.
        subs=str.maketrans('₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜ','0123456789+-=()aeoxhklmnpst')
        previous=0
        for match in re.finditer(r'([A-Za-z])([₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜ]+)',str(text)):
            if match.start()>previous:math_run(math_node,str(text)[previous:match.start()])
            index=OxmlElement('m:sSub');base=OxmlElement('m:e');sub=OxmlElement('m:sub')
            math_run(base,match[1]);math_run(sub,match[2].translate(subs))
            index.extend([base,sub]);math_node.append(index);previous=match.end()
        if previous<len(str(text)):math_run(math_node,str(text)[previous:])
        p._p.append(math_node)
        md.append('`'+str(text).replace('`','')+'`\n')
    outputs=model['observables']
    output_label=lambda name:outputs[name].get('label',name)
    subject=definition.get('name','自建模型')
    if not re.search(r'[\u4e00-\u9fff]',subject):
        subject=output_label(next(iter(outputs)))+' 模型' if len(outputs)==1 else '多指标模型'
    title=subject+'研究检验报告'
    doc.add_paragraph(title,style='Title')
    md.append('# '+title+'\n')
    paragraph(CONCLUSIONS.get(state.get('conclusion'),state.get('conclusion','研究未形成结论'))+'。'
        '本文核对同一模型、固定研究协议和实际试验的结果。数值通过不自动证明领域机制或政策因果有效。')
    paragraph('研究变量：'+'；'.join(output_label(name)+'（'+spec['unit']+'）' for name,spec in outputs.items())
        +'。方法与实际数据依据见正文；原始研究需求全文保留在附录。')
    selected=state.get('selection')
    analysis=facts['presentation']['analysis']
    heading('主要发现')
    if selected:
        paragraph('固定训练短名单为候选 '+ '、'.join(str(i) for i in state['shortlist'])
            +'；验证选择候选 '+str(selected['candidate'])+'，参数 '+pairs(selected['parameters'])
            +'，验证损失 '+number(selected['loss'])+'。'
            +('留出只评价这一选择，没有参与重新选型。' if state.get('holdout') else '留出尚未评分，不能据其评价这一选择。'))
        trained=[row for row in state.get('training',[]) if row.get('status')=='evaluated' and row.get('loss') is not None]
        if trained:
            best=min(trained,key=lambda row:row['loss'])
            if best['candidate']!=selected['candidate']:
                paragraph('训练损失最低的是候选 '+str(best['candidate'])+'（'+pairs(best['parameters'])
                    +'，损失 '+number(best['loss'])+'），与验证选择不同；选型遵循事前验证规则。'
                    '这种差异提示所检查分区的排序发生变化，本身不识别造成变化的领域机制。')
    else:paragraph('未取得可用参数选择，报告保留已执行结果和实际失败，未补造最终模型。')
    for row in analysis['trajectories']:
        paragraph(output_label(row['observable'])+' 在实际结果运行的 t='+number(row['start_time'])+' 至 '+number(row['end_time'])
            +' '+model['time_unit']+'，从 '+number(row['start'])+' 变为 '+number(row['end'])+' '+row['unit']
            +'，净变化 '+number(row['change'])+' '+row['unit']
            +('（相对初值 '+number(100*row['relative_change'])+'%）' if row['relative_change'] is not None else '')+'。')
    for name in outputs:
        available=[r for r in analysis['residuals'] if r['observable']==name]
        if not available:continue
        row=available[-1]  # latest actually scored partition, never an unscored holdout
        paragraph(output_label(name)+' 的'+ROLES[row['role']]+'分区包含 '+str(row['observation_count'])+' 个实际观测、'
            +str(len(row['seeds']))+' 个实际种子，逐点残差 RMSE 为 '+number(row['rmse'])+' '+row['unit']
            +'，偏差均值为 '+number(row['mean_error'])+' '+row['unit']+'。'
            +str(row['actual_point_count'])+' 个实际残差中，正值 '+str(row['positive'])+' 个、负值 '
            +str(row['negative'])+' 个、零值 '+str(row['zero'])+' 个；这描述误差方向，不是独立样本的显著性结论。')
    paragraph('研究编号：'+facts['study_id']+'；模型编号：'+model['model_id'])
    paragraph('模型名称：'+definition.get('name',model['model_id']))
    if protocol.get('baseline'):
        baseline=protocol['baseline']
        paragraph('模型基线运行：'+baseline['run_id']+'；批准方案：'+baseline['design_id'])
        paragraph('本研究沿用该基线的实际模型、输入和时钟。拟合、验证与留出使用随后分别执行的候选试验，基线轨迹没有充当候选结果。')
    if facts.get('result_run'):
        result=facts['result_run']
        paragraph('科研结果运行：'+result['run_id']+'。大屏、状态和该报告实际完整轨迹对应同次归档。'+result['scope'])
    heading('建模方案与实际数学规则')
    paragraph('时间单位：'+model['time_unit']+'；模型类型：'+definition['kind'])
    if definition['kind']=='program':
        for item in definition.get('equations',[]):
            paragraph(item['id']+'：'+item['meaning']+'；实际函数 '+item['function']);expression(item['expression'])
        solver=definition.get('solver',{})
        paragraph('实际数值方法：'+solver.get('method','未声明')+'。'+solver.get('description',''))
    else:
        for key,rule in definition.get('initial_state',{}).items():expression(f'{key}(0) = {rule}')
        for key,rule in definition.get('rates',{}).items():expression(f'd{key}/dt = {rule}')
        for key,rule in (definition.get('agents') or {}).get('update',{}).items():expression(f'{key}(t+dt) = {rule}')
    for name,spec in model['observables'].items():
        paragraph('实际观测 '+name+'，单位 '+spec['unit']).paragraph_format.keep_with_next=True
        expression(spec.get('equation',name))
    method=facts['presentation']['execution_method']
    if method:
        paragraph('以下数值推进规则取自实际运行 '+str(method['origin_run_id'])+' 的归档实现说明。')
        for instruction in method['integration']:paragraph(instruction)
        for equation in method['integration_equations']:expression(equation['expression'])
        if method['integration_equations']:
            paragraph('S 表示实际存量向量，F 为上述实际微分方程。四个子步分别使用对应的子步存量和时间；'
                '同一宏步的主体聚合量在四个子步间保持旧值。步长、终点和实际参数沿用本研究归档，不由说明文字另改。')
    for label,key in [('建模者声明的机制','mechanisms'),('声明的假设','assumptions'),('声明的适用限制','limitations')]:
        for value in definition.get(key,[]):paragraph(label+'：'+value)
    heading('参数 数据与事前研究设计')
    actual_parameters=facts['presentation']['actual_parameters']
    paragraph('本研究参数依据：'+actual_parameters['basis']+'。')
    for name,spec in definition.get('parameters',{}).items():
        grid=protocol['param_grid'].get(name)
        effective=actual_parameters['values'].get(name)
        used=(json.dumps(effective,ensure_ascii=False,allow_nan=False) if name in actual_parameters['values']
              else '尚未取得实际值')
        paragraph(f"{name}：模型默认值 {number(spec.get('default'))}；本研究实际开始值 {used}，单位 {spec.get('unit','未声明')}。"
            +('搜索值为 '+ '、'.join(number(value) for value in grid)+'。' if grid else
              '本次不参与参数搜索；数据绑定与实际执行记录见下文及复核包。'))
    paragraph('验证选型：'+(pairs(selected['parameters']) if selected else '未取得可用选择'))
    split=evaluation['targets']['split']
    paragraph(f"按同一模型时钟划分：t≤{split['training_end']}为训练，随后至{split['validation_end']}为验证，再之后为留出。短名单数量为{protocol['selection_top']}，种子为{protocol['seeds']}。")
    for source_index,source in enumerate(evaluation['targets'].get('sources',[]),1):
        counts=source['counts']
        paragraph('目标来源 '+str(source_index)+' '+source['source']+'，数据编号 '+source['dataset_id']+'。'
            +f"保留原始观测中的训练 {counts['training']} 条、验证 {counts['validation']} 条和留出 {counts['holdout']} 条。许可记录为 {source.get('license','未声明')}。")
        for name,transform in source.get('transforms',{}).items():
            paragraph(f"{name} 映射：源字段 {transform.get('field',transform.get('pointer','未声明'))}，"
                f"{transform.get('source_unit')} → {transform.get('target_unit')}；"
                f"倍率 {number(transform.get('scale'))}，偏移 {number(transform.get('offset'))}。")
    for binding in evaluation['targets']['bindings']:
        paragraph('目标数据映射：'+binding['dataset_id']+' → '+binding['observable']+'；时间原点 '+binding['time_origin'])
    audit=evaluation['input_audit']
    paragraph('信息口径：'+('按声明的信息可用时间检查预测输入。' if audit['information_mode']=='forecast' else
        '回溯条件分析；不能解释为当时已知信息的实时预测。'))
    for limitation in audit.get('limits',[]):paragraph(limitation+'。')
    for item in evaluation['input_evidence']:
        paragraph('实际运行输入 '+item['dataset_id']+' → '+str(item.get('port',item.get('parameter')))
            +'；保留记录 '+str(item.get('records_used'))+' 条。字段转换和完整快照的哈希见复核包。')
    if facts['presentation']['runtime_text_inputs']:
        heading('实际绑定的单记录文字资料')
        paragraph('以下文字从本研究已经冻结的实际输入绑定重新核对原件与字段，不是运行后新加的建模依据；端口传入不单独证明机制有效。')
        for item in facts['presentation']['runtime_text_inputs']:
            paragraph(item['port']+'：'+item['source']+'；数据编号 '+item['dataset_id']
                +'；源路径 '+(item['path'] or '根节点')+'，原记录序号 '+str(item['source_row_index'])+'。')
            for name,field in item['fields'].items():
                paragraph(name+'（原字段 '+field['source_field']+'）：'+field['text'])
            paragraph('原件 SHA256 '+item['sha256']+'；解析 SHA256 '+item['data_sha256']+'。')
    if facts.get('source_evidence'):
        heading('来源文字证据与计量口径')
        paragraph(facts['source_evidence']['scope'])
        for source in facts['source_evidence']['records']:
            paragraph(source['id']+'：'+source['source']+'；数据编号 '+source['dataset_id']
                +'；用途 '+source['purpose']+'；关联 '+', '.join(source['applies_to'])+'。'+source['basis'])
            for name,excerpt in source['fields'].items():
                paragraph(name+'（原字段 '+excerpt['pointer']+'）：'+excerpt['text'])
            paragraph('上述文字是保存原件中的引用，未代替模型数值输入、误差检验或因果识别。原件、解析和引用文字hash见source_evidence.json与复核包。')
    paragraph('误差定义：逐观测计算预测减观测，用事前尺度标准化并平方；每个指标取均值后按正权重平均。随机重复对逐次损失求均值，不用平均预测代替。')
    for name,obj in evaluation['objectives'].items():
        paragraph(f"{name}：权重 {number(obj['weight'])}，尺度 {number(obj['scale'])} {obj['unit']}，"
            +'依据 '+obj['declaration'].get('basis','只用训练观测计算标准差')+'。')
    heading('主要结果与实际误差')
    for role in ROLES:
        item=(state.get('holdout') if role=='holdout' else next((r for r in state.get(role,[])
            if selected and r['candidate']==selected['candidate']),None))
        if item:
            threshold=protocol['max_loss'][role]
            verdict=('未事前设置阈值' if threshold is None else '通过阈值' if item['loss'] is not None and item['loss']<=threshold else '未通过阈值')
            paragraph(ROLES[role]+f"损失 {number(item['loss'])}，事前阈值 {number(threshold)}；{verdict}。")
            repeat=item['replicate_summary']
            deterministic=(definition['kind']=='stocks' or any(
                spec.get('kind')=='time_refinement' and spec.get('dynamics')=='deterministic'
                for spec in protocol.get('diagnostics',[])))
            if repeat['sample_sd'] is not None:
                repeat_text=f"损失样本标准差 {number(repeat['sample_sd'])}，均值标准误 {number(repeat['mean_standard_error'])}。"
            elif repeat['completed']!=repeat['requested'] or item['failed_seeds']:
                repeat_text='存在未完成或失败的重复，未估计有效标准差和标准误。'
            elif repeat['requested']==1:
                repeat_text=('按事前确定性协议完成单次求值，不据此构造随机置信区间。' if deterministic else
                    '本协议声明并完成一个种子，未估计随机重复的标准差和标准误；这不表示执行失败。')
            else:
                repeat_text='没有可报告的有效重复离散度估计，未补造标准差和标准误。'
            paragraph(f"完成 {repeat['completed']} / {repeat['requested']} 次重复。"
                +repeat_text)
            if item['failed_seeds']:paragraph('失败种子：'+'、'.join(str(seed) for seed in item['failed_seeds'])+'。')
        else:paragraph(ROLES[role]+'尚未取得所选模型的实际评分；不补造误差。')
    if not state.get('holdout'):paragraph('留出未评分。此前阶段失败或未取得可用参数，本报告不据留出观测评价模型。')
    if analysis['residuals']:
        heading('分区误差与方向')
        numeric_table(['指标 分区','观测数','偏差均值','MAE','RMSE','最大绝对误差'],[
            [output_label(row['observable'])+'\n'+ROLES[row['role']]+' '+row['unit'],str(row['observation_count']),
             number(row['mean_error']),number(row['mae']),number(row['rmse']),number(row['max_abs_error'])]
            for row in analysis['residuals']],[1.35,.55,1.15,1.15,1.15,1.5])
        paragraph('表中误差保留原指标单位，来自全部已执行种子的逐点预测减观测；各角色的优化损失仍按事前尺度、权重与逐次运行规则计算。')
        for row in analysis['residuals']:
            paragraph(output_label(row['observable'])+' '+ROLES[row['role']]+'：时段 t='+number(row['start_time'])+' 至 '+number(row['end_time'])
                +'，实际种子 '+ '、'.join(map(str,row['seeds']))+'，共 '+str(row['actual_point_count'])+' 个逐次残差；'
                +'正/负/零为 '+str(row['positive'])+'/'+str(row['negative'])+'/'+str(row['zero'])+'。'
                +'最大绝对误差 '+number(row['max_abs_error'])+' '+row['unit']+' 出现在 t='+number(row['max_error_time'])
                +'、种子 '+str(row['max_error_seed'])+'。时间相关误差不自动视为独立重复。')
    heading('候选参数与全部实际求值')
    paragraph('本研究保存 '+str(len(facts['trials']))+' 次候选求值，以下逐项列出候选、实际参数、分区、种子、执行状态及损失。'
        '表中数值按十位有效数字显示，完整精度、运行目录与失败原文保留于 candidate_trials.csv 和复核包；未求值的候选分区不补零。')
    numeric_table(['候选','候选参数','分区','种子','状态','损失'],[
        [str(row['candidate']),pairs(row['receipt']['parameters']),ROLES[row['role']],str(row['seed']),
         '已求值' if row['status']=='evaluated' else '失败',number(row['loss'])]
        for row in facts['trials']],[.45,2.6,.6,.55,.7,1.95])
    for figure in figures:
        heading(figure['title'])
        p=doc.add_paragraph();p.paragraph_format.keep_with_next=True
        run=p.add_run();inline=run.add_picture(str(folder/figure['file']),width=Inches(6.85))
        inline._inline.docPr.set('descr',figure['caption'])
        doc.add_paragraph(figure['caption'],style='Caption')
        md.extend(['!['+figure['title']+']('+figure['file']+')\n',figure['caption']+'\n'])
        if figure.get('diagnostic_id'):
            report=next(row for row in facts['diagnostics']['reports'] if row['id']==figure['diagnostic_id'])
            paragraph('事前依据：'+report['specification']['basis'])
            if report['kind']=='ablation':
                paragraph('消融机制：'+report['specification']['mechanism']+'；实际控制设置 '+pairs(report['specification']['parameters'])
                    +'；实现引用 '+ '、'.join(report['specification']['rule_refs'])+'。')
            for row in analysis['diagnostic_comparisons']:
                if row['id']!=figure['diagnostic_id'] or row['observable']!=figure['observable']:continue
                paragraph('实际比较 '+row['variant']+'（'+pairs(row['parameters'])+'；dt='+number(row['dt'])+'）：'
                    +'共同终点 t='+number(row['end_time'])+' 的基准均值为 '+number(row['baseline_end_mean'])+' '+row['unit']
                    +'，对照均值为 '+number(row['variant_end_mean'])+' '+row['unit']+'，对照减基准为 '
                    +number(row['end_mean_difference'])+' '+row['unit']+'；全部共同观测时点中最大均值绝对差为 '
                    +number(row['max_abs_mean_difference'])+' '+row['unit']+'，出现在 t='+number(row['max_mean_difference_time'])
                    +'。每组实际重复 '+str(row['replicates'])+' 次。')
            if report['kind']!='time_refinement':
                paragraph('上述差异来自已执行的模型内部对照，未据此识别现实政策因果，也未证明该机制是唯一解释。')
    heading('诊断解释与失败记录')
    paragraph(facts['summary']['diagnostic_scope'])
    for report in (facts.get('diagnostics') or {}).get('reports',[]):
        paragraph(report['id']+'：'+report['status']+'。'+report['scope'])
        if report['kind']=='time_refinement':
            from .model_diagnostics import CURRENT_COMPARISON_RULE
            paragraph('比较口径：'+('全部声明的细化档各自对首档基线，在共同物理时点核对；对所有档/时点/指标取最大差异。'
                if report.get('comparison_rule')==CURRENT_COMPARISON_RULE else
                '历史旧规则，仅以最细档对基线判定，不能证明中间档通过；此处保留原记录。'))
            paragraph('最大标准化细化差异 '+str(report['max_scaled_change'])+'；事前阈值 '+str(report['specification']['max_scaled_change'])+'。经验阶及各实际时点见事实文件，不作为全局收敛证明。')
    failures=[trial for trial in facts['trials'] if trial['status']!='evaluated']
    if not failures:paragraph('本研究记录中没有失败的拟合求值。该陈述不评价其他研究或原生建模成功率。')
    for trial in failures:paragraph('失败试验 '+trial['directory']+'：'+json.dumps(trial['receipt'].get('error'),ensure_ascii=False))
    if state.get('error'):paragraph('研究阶段错误：'+str(state['error']))
    if protocol.get('diagnostic_implementation_binding'):
        binding=protocol['diagnostic_implementation_binding']
        heading('消融科学声明与实际实现')
        paragraph('消融参数、机制、输出和判据在研究准备时冻结，后续只绑定实现。获审方案 '+binding['design_id']
            +'，方案 hash '+binding['plan_sha256']+'，实际模型定义 hash '+binding['model_definition_sha256']+'。')
        for row in binding['mappings']:paragraph(row['id']+' → '+ '、'.join(row['rule_refs'])+'。'+row['reason'])
    heading('结论范围与复核依据')
    for text in facts['interpretation_limits']:paragraph(text+'。')
    if state.get('exposure'):paragraph('留出使用记录：'+state['exposure']['independence_status']+'。'+state['exposure']['scope'])
    paragraph('报告由研究事实生成，全部图表的原数值、原始数据文件、实际模型定义、求值清单和求解环境保存在同一复核包。复算仍需要相同平台源码版本和相应执行环境。')
    hashes=[('平台源码',evaluation['source_fingerprint']),('研究协议',protocol['sha256']),('报告证据',facts['evidence_sha256'])]
    for source_index,source in enumerate(evaluation['targets']['sources'],1):
        hashes.append(('目标来源 '+str(source_index),source['sha256']))
    table=doc.add_table(rows=0,cols=2);table.autofit=False
    table.columns[0].width=Inches(1.45);table.columns[1].width=Inches(5.4)
    borders=OxmlElement('w:tblBorders')
    for edge in ('top','left','bottom','right','insideH','insideV'):
        border=OxmlElement('w:'+edge);border.set(qn('w:val'),'single');border.set(qn('w:sz'),'4');border.set(qn('w:color'),'D9D9D9');borders.append(border)
    table._tbl.tblPr.append(borders)
    for index,(label,sha) in enumerate([('复核项目','SHA256'),*hashes]):
        row=table.add_row();row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        cells=row.cells
        for cell,text in zip(cells,(label,sha)):
            cell.vertical_alignment=1
            p=cell.paragraphs[0];p.paragraph_format.space_after=Pt(0);p.paragraph_format.space_before=Pt(0)
            p.paragraph_format.line_spacing=1.0
            run=p.add_run(text);run.font.size=Pt(9);run.bold=index==0
            if index==0:
                shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'E8EEF3');cell._tc.get_or_add_tcPr().append(shade)
        md.append(label+' SHA256 '+sha+'\n')
    doc.core_properties.author='DAYAN'
    doc.core_properties.title=title
    if definition.get('description'):
        heading('附录 建模说明原文')
        paragraph('以下为实际模型定义保存的建模说明。实际方程、求解推进、参数和试验记录见正文及复核包；说明文字本身不代替运行证据。')
        paragraph(definition['description'])
    heading('附录 原始研究需求全文')
    paragraph(protocol['question'])
    doc.save(folder/'research.docx')
    (folder/'research.md').write_text('\n'.join(md),encoding='utf-8')


def generate_report(study_id,kind='academic'):
    if kind!='academic':raise ValueError('自建模型科研报告当前提供academic，不能用另一标签冒充不同研究内容')
    from .. import datasets
    folder=studies.directory(study_id)
    with file_lock(folder/'study.lock',timeout=.1):
        facts=evidence(study_id)
        renderer=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        report_id='MR-'+digest({'evidence':facts['evidence_sha256'],'renderer':renderer})[:24]
        target=folder/'reports'/report_id
        with file_lock(target/'report.lock',timeout=.1):
            receipt_path=target/'receipt.json'
            if receipt_path.exists():
                receipt=read_json(receipt_path)
                if receipt['evidence_sha256']==facts['evidence_sha256']:
                    if any(hashlib.sha256((target/name).read_bytes()).hexdigest()!=sha for name,sha in receipt['files'].items()):
                        raise ValueError('已发布科研报告文件哈希不一致，不能静默覆盖')
                    return receipt
            target.mkdir(parents=True,exist_ok=True)
            figures=_figures(facts,target)
            _document(facts,figures,target)
            atomic_json(target/'research.facts.json',{**facts,'figures':figures})
            _csv(target/'predictions.csv',facts['selected_predictions'],
                ['role','candidate','seed','observable','time','unit','value','predicted','residual_predicted_minus_observed','scaled_squared_error','provenance'])
            _csv(target/'candidate_trials.csv',[{**row,'parameters':row['receipt']['parameters'],
                'error':row['receipt'].get('error')} for row in facts['trials']],
                ['role','candidate','seed','parameters','status','loss','error','directory'])
            diag_rows=[{'diagnostic':report['id'],'variant':profile['label'],'dt':profile['dt'],
                'parameters':profile['parameters'],'time':point['sim_t'],'observable':name,**metrics}
                for report in (facts.get('diagnostics') or {}).get('reports',[]) for profile in report['profiles']
                for point in profile['points'] for name,metrics in point['metrics'].items()]
            _csv(target/'diagnostics.csv',diag_rows,
                ['diagnostic','variant','dt','parameters','time','observable','mean','sample_sd','mean_standard_error','values'])
            names=['research.docx','research.md','research.facts.json','predictions.csv','candidate_trials.csv','diagnostics.csv',
                   *[figure['file'] for figure in figures]]
            if facts.get('source_evidence'):
                atomic_json(target/'source_evidence.json',facts['source_evidence'])
                names.append('source_evidence.json')
            ids={b['dataset_id'] for b in facts['protocol']['evaluation']['targets']['bindings']}
            ids.update(b['dataset_id'] for b in facts['protocol']['evaluation']['execution']['data_bindings'])
            ids.update(row['dataset_id'] for row in facts.get('source_evidence',{}).get('records',[]))
            with ZipFile(target/'reproducibility.zip','w',ZIP_DEFLATED) as archive:
                for name in names:archive.write(target/name,'reports/'+name)
                for name in ('protocol.json','state.json'):archive.write(folder/name,name)
                if facts.get('result_run'):
                    from ..run_store import get_store
                    run_folder=get_store()._path(facts['result_run']['run_id'])
                    for name in ('metadata.json',*facts['result_run']['archive_files']):
                        archive.write(run_folder/name,'selected_result/'+name)
                for trial in facts['trials']:
                    for name in ('request.json','result.json','fit.json','manifest.json','observations.json'):
                        path=folder/trial['directory']/name
                        if path.exists():archive.write(path,path.relative_to(folder).as_posix())
                if facts.get('diagnostics'):
                    for name in ('protocol.json','result.json'):archive.write(folder/'diagnostics'/name,'diagnostics/'+name)
                    for trial in facts['diagnostics']['trials'].values():
                        for name in ('request.json','result.json','fit.json','manifest.json','observations.json'):
                            path=folder/'diagnostics'/trial['directory']/name
                            if path.exists():archive.write(path,path.relative_to(folder).as_posix())
                for dataset_id in sorted(ids):
                    record=datasets.load(dataset_id)
                    archive.write(datasets.dataset_dir()/dataset_id/'original','datasets/'+dataset_id+'/original')
                    archive.writestr('datasets/'+dataset_id+'/record.json',json.dumps(record,ensure_ascii=False))
            names.append('reproducibility.zip')
            root=f'/api/research/studies/{study_id}/reports/{report_id}/files/'
            receipt={'study_id':study_id,'status':facts['state']['status'],'conclusion':facts['state'].get('conclusion'),
                'report_id':report_id,'renderer_sha256':renderer,
                'created_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'evidence_sha256':facts['evidence_sha256'],'protocol_sha256':facts['protocol']['sha256'],
                'figure_count':len(figures),'path':str(target/'research.docx'),'file':root+'research.docx',
                'facts_url':root+'research.facts.json','bundle_url':root+'reproducibility.zip',
                'files':{name:hashlib.sha256((target/name).read_bytes()).hexdigest() for name in names}}
            atomic_json(receipt_path,receipt)
    return receipt


def _compatible_evidence_ids(facts):
    """Recognize the exact prior v1 summary before its limitation was exposed.

    Only two derived summary fields differ. Protocol, actual trials, selection,
    diagnostics, inputs and selected run remain in the hash without exclusions.
    """
    from .model_diagnostics import LEGACY_COMPARISON_RULE
    ids={facts['evidence_sha256']}
    summary=facts['summary']
    prior_scope='已事前声明，完整试验和比较保存在同研究diagnostics目录'
    legacy_note='；历史旧规则仅以最细档对基线判定，不能证明中间细化档通过；原记录保留，未冒充新版检查'
    if (facts['protocol'].get('diagnostic_comparison_rule',LEGACY_COMPARISON_RULE)==LEGACY_COMPARISON_RULE
            and summary.get('diagnostic_comparison_rule')==LEGACY_COMPARISON_RULE
            and summary.get('diagnostic_scope')==prior_scope+legacy_note):
        prior=deepcopy({key:value for key,value in facts.items() if key not in ('evidence_sha256','presentation')})
        prior['summary'].pop('diagnostic_comparison_rule')
        prior['summary']['diagnostic_scope']=prior_scope
        ids.add(digest(prior))
    return ids


def _report_receipt(study_id,report_id,*,evidence_sha256=None):
    if not re.fullmatch(r'MR-[a-f0-9]{24}',str(report_id)):raise ValueError('非法report_id')
    folder=studies.directory(study_id)/'reports'/report_id
    receipt=read_json(folder/'receipt.json')
    expected='MR-'+digest({'evidence':receipt['evidence_sha256'],'renderer':receipt['renderer_sha256']})[:24]
    if (receipt['study_id']!=study_id or receipt['report_id']!=report_id or report_id!=expected
            or evidence_sha256 is not None and receipt['evidence_sha256'] not in evidence_sha256):
        raise ValueError('报告与研究证据或生成版本不一致')
    if not isinstance(receipt.get('files'),dict) or not receipt['files']:
        raise ValueError('报告缺少实际文件清单')
    return folder,receipt


def report_index(study_id):
    facts=evidence(study_id)
    expected=_compatible_evidence_ids(facts)
    rows=[]
    current_renderer=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for path in sorted((studies.directory(study_id)/'reports').glob('MR-*/receipt.json')):
        try:
            folder,receipt=_report_receipt(study_id,path.parent.name,evidence_sha256=expected)
            for filename in receipt['files']:_published_file(folder,receipt,filename)
            chart_facts=read_json(folder/'research.facts.json')
            rows.append({**{key:receipt[key] for key in ('study_id','report_id','status','conclusion','figure_count',
                                                    'file','facts_url','bundle_url','evidence_sha256','renderer_sha256','files')},
                         'figure_files':[name for name in receipt['files'] if re.fullmatch(r'figure_\d+\.png',name)],
                         'figure_assets':[{key:figure[key] for key in ('file','title','caption')}
                                          for figure in chart_facts['figures']],
                         'current_renderer':receipt['renderer_sha256']==current_renderer,
                         'created_at':receipt.get('created_at'),
                         '_file_time':path.stat().st_mtime_ns,
                         'historical_diagnostic_scope':receipt['evidence_sha256']!=facts['evidence_sha256'],
                         **({'historical_scope_note':facts['summary']['diagnostic_scope']}
                            if receipt['evidence_sha256']!=facts['evidence_sha256'] else {})})
        except (ValueError,OSError,KeyError) as exc:
            rows.append({'study_id':study_id,'report_id':path.parent.name,'status':'integrity_failed','error':str(exc)})
    # A content hash is not chronology. Prefer the verified current renderer;
    # retained versions fall back to receipt file time, never lexical MR order.
    rows.sort(key=lambda row:(row['status']=='integrity_failed',not row.get('current_renderer',False),
                              row.get('historical_diagnostic_scope',True),-row.get('_file_time',0)))
    for row in rows:row.pop('_file_time',None)
    return rows


def _published_file(folder,receipt,filename):
    if (not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',filename) or filename not in receipt['files']):
        raise ValueError('报告文件不在此版本已发布清单内')
    path=(folder/filename).resolve()
    if path.parent!=folder.resolve() or hashlib.sha256(path.read_bytes()).hexdigest()!=receipt['files'][filename]:
        raise ValueError('科研报告文件哈希或路径不一致')
    return path


def report_file(study_id,report_id,filename):
    expected=_compatible_evidence_ids(evidence(study_id))
    folder,receipt=_report_receipt(study_id,report_id,evidence_sha256=expected)
    return _published_file(folder,receipt,filename)
