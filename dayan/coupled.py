"""Explicit synchronous SD/ABM coupling with reproducible clock and ports.

The wage proxy and feedback law are declared mechanism assumptions. No currency,
empirical calibration or classical bounds are inferred from this experiment.
"""
from __future__ import annotations
import copy
import math
import numpy as np


class GoodwinSDCore:
    """RK4: dw=w*(-a+b*l); dl=l*((1-w)/nu-delta).

    Positive Lotka-Volterra orbits conserve
    H=w/nu-(1/nu-delta)*log(w)+b*l-a*log(l).
    Classical equations do not guarantee fractions <=1 for arbitrary initial
    states. Values are never clipped to manufacture economic validity.
    """
    def __init__(self,nu=2.5,delta=.03,a=.045,b=.06,x0=None):
        if any(not math.isfinite(v) or v<=0 for v in (nu,delta,a,b)) or nu*delta>=1:
            raise ValueError('Goodwin需要正有限参数及nu*delta<1')
        self.nu,self.delta,self.a,self.b=nu,delta,a,b
        self.x=np.array(x0 if x0 is not None else [(1-nu*delta)*.95,(a/b)*1.05],float)
        if self.x.shape!=(2,) or not np.isfinite(self.x).all() or (self.x<=0).any():
            raise ValueError('Goodwin初态须为两个正有限数')

    def derivatives(self,x):
        w,lmb=x
        return np.array([w*(-self.a+self.b*lmb),lmb*((1-w)/self.nu-self.delta)])

    def invariant(self):
        w,lmb=self.x
        return float(w/self.nu-(1/self.nu-self.delta)*np.log(w)+self.b*lmb-self.a*np.log(lmb))

    def step(self,dt):
        if not math.isfinite(dt) or dt<=0:raise ValueError('dt须为正有限数')
        x=self.x;k1=self.derivatives(x);k2=self.derivatives(x+dt*k1/2)
        k3=self.derivatives(x+dt*k2/2);k4=self.derivatives(x+dt*k3)
        result=x+dt/6*(k1+2*k2+2*k3+k4)
        if not np.isfinite(result).all() or (result<=0).any():
            raise ValueError('Goodwin数值状态失效，请缩小步长；未裁剪结果')
        self.x=result


class MicroABMSector:
    """Heterogeneous reservation-wage mechanism; wages are normalized proxies."""
    BASE_DT=.1
    def __init__(self,n=200,seed=0):
        if isinstance(n,bool) or not isinstance(n,int) or not 1<=n<=5000:raise ValueError('主体数须为1..5000整数')
        self.rng=np.random.default_rng(seed);self.n=n
        self.employed=np.zeros(n,bool);self.reservation=self.rng.uniform(.4,.95,n);self.wage=.7

    def set_wage_level(self,w):
        if not math.isfinite(w) or w<0:raise ValueError('工资代理须非负有限')
        self.wage=float(w)

    def step(self,dt=.1):
        if not math.isfinite(dt) or dt<=0:raise ValueError('dt须为正有限数')
        base_join=np.clip((self.wage-self.reservation)/.3,0,.6)
        base_leave=np.clip((self.reservation-self.wage)/.5,0,.3)
        # Convert the explicitly defined .1-time transition to equal hazards.
        p_join=-np.expm1(np.log1p(-base_join)*dt/self.BASE_DT)
        p_leave=-np.expm1(np.log1p(-base_leave)*dt/self.BASE_DT)
        draws=self.rng.random(self.n)
        self.employed=np.where(self.employed,draws>=p_leave,draws<p_join)

    def get_employment_rate(self):return float(self.employed.mean())

    def money(self):
        """Virtual wage bill, not a conservation law or a monetary ledger."""
        return float(self.employed.sum()*self.wage)


class CoupledSimulation:
    """Jacobi-style sample at start, operator-split SD feedback then RK4 and ABM."""
    def __init__(self,mode='one-way',n_micro=200,seed=0,T=200.,dt=.1):
        if mode not in ('one-way','cyclic','reference'):raise ValueError('未知耦合模式')
        if not math.isfinite(T) or not math.isfinite(dt) or T<=0 or dt<=0:raise ValueError('T/dt须为正有限数')
        from .runtime import validate_run_arguments
        validate_run_arguments(math.ceil(T/dt),dt,seed)
        self.mode,self.T,self.dt,self.seed=mode,float(T),float(dt),seed
        self.sd=GoodwinSDCore();self.abm=MicroABMSector(n_micro,seed)
        self.t=0.;self.history=[];self.port_trace=[]

    def _record(self):
        self.history.append({'t':self.t,'wage_share':float(self.sd.x[0]),'employment_sd':float(self.sd.x[1]),
                             'employment_abm':self.abm.get_employment_rate(),'wage_proxy_abm':self.abm.wage})

    def step(self,dt=None):
        h=min(self.dt if dt is None else dt,self.T-self.t)
        if h<=0:return
        start=self.t;macro=float(self.sd.x[1]);micro=self.abm.get_employment_rate()
        feedback=0.
        if self.mode!='reference':self.abm.set_wage_level(.7*macro)
        if self.mode=='cyclic':
            feedback=float(np.clip(.05*(micro-macro),-.01,.01))
            self.sd.x[1]+=h*feedback
        self.sd.step(h);self.abm.step(h);self.t=min(self.T,round(start+h,12))
        self.port_trace.append({'source_t':start,'target_t':self.t,'mode':self.mode,
            'employment_sd_source':macro,'employment_abm_source':micro,
            'wage_proxy_applied':self.abm.wage,'feedback_rate_applied':feedback,
            'units':{'employment':'fraction','wage':'normalized_proxy','feedback':'fraction/model_time'},
            'order':'sample_start -> SD_feedback -> SD_RK4 + ABM_hazard -> record_common_end'})
        self._record()

    def run(self):
        if not self.history:self._record()
        while self.t<self.T-1e-12:self.step()
        return self.summary()

    def snapshot(self):
        return copy.deepcopy({'version':1,'mode':self.mode,'T':self.T,'dt':self.dt,'seed':self.seed,'t':self.t,
            'sd':{'params':{k:getattr(self.sd,k) for k in ('nu','delta','a','b')},'x':self.sd.x.tolist()},
            'abm':{'n':self.abm.n,'employed':self.abm.employed.tolist(),'reservation':self.abm.reservation.tolist(),
                   'wage':self.abm.wage,'rng_state':self.abm.rng.bit_generator.state},
            'history':self.history,'port_trace':self.port_trace})

    def restore(self,state):
        state=copy.deepcopy(state)
        if state.get('version')!=1:raise ValueError('不支持的耦合检查点')
        self.__init__(state['mode'],state['abm']['n'],state['seed'],state['T'],state['dt'])
        self.t=state['t'];self.sd=GoodwinSDCore(**state['sd']['params'],x0=state['sd']['x'])
        self.abm.employed=np.array(state['abm']['employed'],bool)
        self.abm.reservation=np.array(state['abm']['reservation'],float);self.abm.wage=state['abm']['wage']
        self.abm.rng.bit_generator.state=state['abm']['rng_state']
        self.history=state['history'];self.port_trace=state['port_trace']

    def summary(self):
        if not self.history:self._record()
        arr=np.array([h['wage_share'] for h in self.history]);sd=np.array([h['employment_sd'] for h in self.history])
        abm=np.array([h['employment_abm'] for h in self.history])
        correlation=float(np.corrcoef(sd,abm)[0,1]) if len(sd)>2 and sd.std()>1e-12 and abm.std()>1e-12 else None
        return {'mode':self.mode,'wage_share_range':float(np.ptp(arr)),'wage_share_final':float(arr[-1]),
                'emp_sd_final':float(sd[-1]),'emp_abm_final':float(abm[-1]),
                'sd_bounded':bool((arr>0).all() and (arr<1).all() and (sd>0).all() and (sd<1).all()),
                'abm_active':bool(abm.max()>0 and abm.min()<1),'corr_sd_abm':correlation,
                'final_t':self.t,'n_steps':len(self.port_trace),
                'assumptions':['工资代理=.7*宏观就业率，无实证货币单位',
                    '反馈率=clip(.05*(微观就业率-宏观就业率),-.01,.01)，单位fraction/model_time',
                    'Goodwin方程不裁剪；sd_bounded只报告本次轨迹是否位于经济比例域，不是任意参数的定理']}
