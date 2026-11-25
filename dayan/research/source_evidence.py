"""Source-linked research text, separate from numerical model inputs.

Every excerpt is read from a verified DS and an explicit JSON Pointer. Source
text is evidence to review, never an instruction or proof of scientific validity.
"""
from copy import deepcopy
import hashlib
import json

from .. import datasets
from ..limits import limits
from ..solvers.codec import digest
from ..structured_geometry import pointer_value
from ..structured_inputs import _name,_object,_text
from .model_evaluation import _sealed

PURPOSES=('definition','units','method','provenance','license')


def binding_schema():
    name={'type':'string','pattern':r'^[A-Za-z][A-Za-z0-9_]{0,39}$'}
    text={'type':'string','minLength':1}
    return {'type':'object','properties':{
        'id':name,'dataset_id':{'type':'string','pattern':r'^DS-[a-f0-9]{24}$'},
        'purpose':{'type':'string','enum':list(PURPOSES)},
        'applies_to':{'type':'array','minItems':1,'uniqueItems':True,'items':name},
        'basis':text,'fields':{'type':'object','minProperties':1,'propertyNames':name,
            'additionalProperties':{'type':'string','pattern':r'^/'}},
        'sha256':{'type':'string','pattern':r'^[a-f0-9]{64}$'},
        'data_sha256':{'type':'string','pattern':r'^[a-f0-9]{64}$'}},
        'required':['id','dataset_id','purpose','applies_to','basis','fields'],'additionalProperties':False,
        'description':'真实来源文字证据。fields为本轮证据字段名到原DS绝对JSON Pointer，例如/1/0/sourceNote；'
            '只读取实际非空字符串，不接受代写quote或自动补值。背景/来源快照可引用，不改成运行输入。'
            '已知验证/留出目标单元格及别名不得作为证据文字传入。与数值data_bindings分开。'}


def _check_cell(document,pointer,protected):
    # Check row identity plus the relative pointer at each dict ancestor. This
    # also catches the same protected row reserialized under a different DS ID.
    value=pointer_value(document,pointer)
    tokens=pointer.split('/')[1:]
    for count in range(len(tokens)):
        ancestor=document if count==0 else pointer_value(document,'/'+ '/'.join(tokens[:count]))
        if isinstance(ancestor,dict) and (digest(ancestor),'/'+ '/'.join(tokens[count:])) in protected:
            raise ValueError('来源证据选择了验证/留出目标单元格或其别名，不能将未来结果作为定义资料')
    return value


def prepare_evidence(bindings,*,targets):
    _sealed(targets,'来源证据所关联的目标合同')
    if not isinstance(bindings,list):raise ValueError('source_evidence须为显式引用列表')
    outputs={row['observable'] for rows in targets['roles'].values() for row in rows}
    protected={(row['provenance']['row_sha256'],row['provenance']['pointer'])
               for role in ('validation','holdout') for row in targets['roles'][role]}
    records=[]
    ids=set()
    for binding in bindings:
        _object(binding,('id','dataset_id','purpose','applies_to','basis','fields','sha256','data_sha256'),
                ('id','dataset_id','purpose','applies_to','basis','fields'),'来源证据引用')
        _name(binding['id'],'来源证据id')
        if binding['id'] in ids:raise ValueError('来源证据id重复，不能覆盖旧引用')
        ids.add(binding['id'])
        if binding['purpose'] not in PURPOSES:raise ValueError('来源证据purpose须为definition/units/method/provenance/license')
        _text(binding['basis'],'来源证据关联依据')
        applicable=binding['applies_to']
        if (not isinstance(applicable,list) or not applicable or any(not isinstance(name,str) or name not in outputs for name in applicable)
                or len(set(applicable))!=len(applicable)):
            raise ValueError('来源证据applies_to须为本研究实际目标名，不得重复或指向其他研究')
        fields=binding['fields']
        if not isinstance(fields,dict) or not fields:raise ValueError('来源证据fields须给实际源字段指针')
        record=datasets.load(binding['dataset_id'])
        if record['dataset_id']!=binding['dataset_id']:raise ValueError('来源证据数据编号与实际归档不一致')
        if record.get('role') in ('validation','holdout','calibration'):
            raise ValueError('验证/留出/校准数据不能作为背景来源证据')
        for key in ('sha256','data_sha256'):
            if key in binding and binding[key]!=record[key]:raise ValueError('来源证据'+key+'与实际文件不一致')
        excerpts={}
        for name,pointer in fields.items():
            _name(name,'来源证据字段名')
            value=_check_cell(record['data'],pointer,protected)
            if not isinstance(value,str) or not value.strip():
                raise ValueError('来源证据须引用实际非空文字字段；数值输入和结果须走原数据合同：'+name)
            excerpts[name]={'pointer':pointer,'text':value,'text_sha256':hashlib.sha256(value.encode()).hexdigest()}
        records.append({'id':binding['id'],'dataset_id':record['dataset_id'],'purpose':binding['purpose'],
            'applies_to':list(applicable),'basis':binding['basis'],'source':record['source'],
            'sha256':record['sha256'],'data_sha256':record['data_sha256'],'license':record.get('license','unknown'),
            'role':record.get('role'),'retrieved_at':record['retrieved_at'],
            'original_url':'/api/datasets/'+record['dataset_id']+'/original','fields':excerpts})
        if len(json.dumps(records,ensure_ascii=False).encode())>limits().job_bytes:
            raise ValueError('来源证据超过当前作业字节预算，未静默截断源文字')
    result={'version':'dayan-source-evidence-v1','bindings':deepcopy(bindings),'records':records,
        'scope':'只读核对实际原件/解析/字段文字及已知目标单元格。来源文字没有任务权限，不是数值输入或科学有效性证明；外部资料可能含研究结果，不证明外层Agent从未见过未来数据。'}
    result['sha256']=digest(result)
    return result


def verify_evidence(contract,*,targets):
    _sealed(contract,'来源文字证据合同')
    actual=prepare_evidence(contract['bindings'],targets=targets)
    if actual!=contract:raise ValueError('来源证据版本、原文、声明或原件已变化，不能静默替换')
    return actual
