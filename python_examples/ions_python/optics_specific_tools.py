import numpy as np

import pymask as pm

# The parts marked by (*) in following need to be
# adapted according to knob definitions

def build_sequence(mad, beam):

    #slicefactor = 2 # For testing
    slicefactor = 8 # For production

    pm.make_links(force=True, links_dict={
        'optics_runII': '/afs/cern.ch/eng/lhc/optics/runII',
        'optics_runIII': '/afs/cern.ch/eng/lhc/optics/runIII',})

    mylhcbeam = int(beam)

    mad.input('ver_lhc_run = 3')

    mad.input(f'mylhcbeam = {beam}')
    mad.input('option, -echo,warn, -info;')

    # optics dependent macros (for splitting)
    mad.call('optics_runII/2018/toolkit/macro.madx')

    # Redefine macros
    _redefine_crossing_save_disable_restore(mad)

    # optics independent macros
    mad.call('tools/optics_indep_macros.madx')

    assert mylhcbeam in [1, 2, 4], "Invalid mylhcbeam (it should be in [1, 2, 4])"

    if mylhcbeam in [1, 2]:
        mad.call('optics_runII/2018/lhc_as-built.seq')
    else:
        mad.call('optics_runII/2018/lhcb4_as-built.seq')

    # New IR7 MQW layout and cabling
    mad.call('optics_runIII/RunIII_dev/IR7-Run3seqedit.madx')

    # Makethin part
    if slicefactor > 0:
        # the variable in the macro is slicefactor
        mad.input(f'slicefactor={slicefactor};')
        mad.call('optics_runII/2018/toolkit/myslice.madx')
        mad.beam()
        for my_sequence in ['lhcb1','lhcb2']:
            if my_sequence in list(mad.sequence):
                mad.input(f'use, sequence={my_sequence}; makethin,'
                     f'sequence={my_sequence}, style=teapot, makedipedge=true;')
    else:
        warnings.warn('The sequences are not thin!')

    # Cycling w.r.t. to IP3 (mandatory to find closed orbit in collision in the presence of errors)
    for my_sequence in ['lhcb1','lhcb2']:
        if my_sequence in list(mad.sequence):
            mad.input(f'seqedit, sequence={my_sequence}; flatten;'
                        'cycle, start=IP3; flatten; endedit;')

def apply_optics(mad, optics_file):
    mad.call(optics_file)
    mad.call('ir7_strengths.madx')


def set_optics_specific_knobs(mad, knob_settings, mode=None):

    # Copy knob settings to mad variable space
    mad.set_variables_from_dict(params=knob_settings)

    # A check
    if mad.globals.nrj < 500:
        assert knob_settings['on_disp'] == 0

    # A knob redefinition
    mad.input('on_alice := on_alice_normalized * 7000./nrj;')
    mad.input('on_lhcb := on_lhcb_normalized * 7000./nrj;')


def twiss_and_check(mad, sequences_to_check, twiss_fname,
        tol_beta=1e-3, tol_sep=1e-6, save_twiss_files=True,
        check_betas_at_ips=True, check_separations_at_ips=True):

    var_dict = mad.get_variables_dicts()
    twiss_dfs = {}
    summ_dfs = {}
    for ss in sequences_to_check:
        mad.use(ss)
        mad.twiss()
        tdf = mad.get_twiss_df('twiss')
        twiss_dfs[ss] = tdf
        sdf = mad.get_summ_df('summ')
        summ_dfs[ss] = sdf

    if save_twiss_files:
        for ss in sequences_to_check:
            tt = twiss_dfs[ss]
            if twiss_fname is not None:
                tt.to_parquet(twiss_fname + f'_seq_{ss}.parquet')

    if check_betas_at_ips:
        for ss in sequences_to_check:
            tt = twiss_dfs[ss]
            _check_beta_at_ips_against_madvars(beam=ss[-1],
                    twiss_df=tt,
                    variable_dicts=var_dict,
                    tol=tol_beta)
        print('IP beta test against knobs passed!')

    if check_separations_at_ips:
        twiss_df_b1 = twiss_dfs['lhcb1']
        twiss_df_b2 = twiss_dfs['lhcb2']
        _check_separations_at_ips_against_madvars(twiss_df_b1, twiss_df_b2,
                var_dict, tol=tol_sep)
        print('IP separation test against knobs passed!')

    other_data = {}
    other_data.update(var_dict)
    other_data['summ_dfs'] = summ_dfs

    return twiss_dfs, other_data

def lumi_control(mad, twiss_dfs, configuration, knob_names):
    from scipy.optimize import least_squares

    # Leveling in IP1, IP2, IP5, IP8
    def function_to_minimize(sep_m):
        my_dict=pm.get_luminosity_dict(
            mad, twiss_dfs, f'ip{ip}', configuration[f'nco_IP{ip}'])
        my_dict[sep_plane + '_1']=np.abs(sep_m)
        my_dict[sep_plane + '_2']=-np.abs(sep_m)
        return np.abs(pm.luminosity(**my_dict) - L_target)
    
    for ip in [1,2,5,8]:
        sep_plane = configuration[f'sep_plane_ip{ip}']
        sep_knobname = knob_names[f'sepknob_ip{ip}_mm']
    
        L_target = configuration[f'lumi_ip{ip}']
        sigma_sep_b1=np.sqrt(twiss_dfs['lhcb1'].loc[f'ip{ip}:1']['bet'+sep_plane]
                   * mad.sequence.lhcb1.beam['e'+sep_plane])
        optres=least_squares(function_to_minimize, sigma_sep_b1)
        mad.globals[sep_knobname]=(np.sign(mad.globals[sep_knobname])
                                    * np.abs(optres['x'][0])*1e3)

def _redefine_crossing_save_disable_restore(mad):

    mad.input('''
    crossing_save: macro = {
    on_x1_aux=on_x1;on_sep1_aux=on_sep1;on_a1_aux=on_a1;on_o1_aux=on_o1;
    on_x2_aux=on_x2;on_sep2_aux=on_sep2;on_a2_aux=on_a2;on_o2_aux=on_o2; on_oe2_aux=on_oe2;
    on_x5_aux=on_x5;on_sep5_aux=on_sep5;on_a5_aux=on_a5;on_o5_aux=on_o5;
    on_x8_aux=on_x8;on_sep8_aux=on_sep8;on_a8_aux=on_a8;on_o8_aux=on_o8;
    on_disp_aux=on_disp;
    on_alice_aux=on_alice;
    on_lhcb_aux=on_lhcb;
    on_ov2_aux=on_ov2;
    on_ov5_aux=on_ov5;
    };

    crossing_disable: macro={
    on_x1=0;on_sep1=0;on_a1=0;on_o1=0;
    on_x2=0;on_sep2=0;on_a2=0;on_o2=0;on_oe2=0;
    on_x5=0;on_sep5=0;on_a5=0;on_o5=0;
    on_x8=0;on_sep8=0;on_a8=0;on_o8=0;
    on_disp=0;
    on_alice=0; on_lhcb=0;
    on_ov2=0;on_ov5=0;
    };

    crossing_restore: macro={
    on_x1=on_x1_aux;on_sep1=on_sep1_aux;on_a1=on_a1_aux;on_o1=on_o1_aux;
    on_x2=on_x2_aux;on_sep2=on_sep2_aux;on_a2=on_a2_aux;on_o2=on_o2_aux; on_oe2=on_oe2_aux;
    on_x5=on_x5_aux;on_sep5=on_sep5_aux;on_a5=on_a5_aux;on_o5=on_o5_aux;
    on_x8=on_x8_aux;on_sep8=on_sep8_aux;on_a8=on_a8_aux;on_o8=on_o8_aux;
    on_disp=on_disp_aux;
    on_alice=on_alice_aux; on_lhcb=on_lhcb_aux;
    on_ov2=on_ov2_aux;
    on_ov5=on_ov5_aux;
    };
    ''')


def _check_beta_at_ips_against_madvars(beam, twiss_df, variable_dicts, tol):
    twiss_value_checks=[]
    for iip, ip in enumerate([1,2,5,8]):
        for plane in ['x', 'y']:
            # (*) Adapt based on knob definitions
            twiss_value_checks.append({
                    'element_name': f'ip{ip}:1',
                    'keyword': f'bet{plane}',
                    'varname': f'bet{plane}ip{ip}b{beam}',
                    'tol': tol[iip]})

    pm.check_twiss_against_madvars(twiss_value_checks, twiss_df, variable_dicts)

def _check_separations_at_ips_against_madvars(twiss_df_b1, twiss_df_b2,
        variables_dict, tol):

    separations_to_check = []
    # IP1
    separations_to_check.append({
            'element_name': f'ip1:1',
            'plane': 'x',
            'varname': 'on_sep1',
            'scale_factor': -2*1e-3,
            'tol': tol[0]})
    # IP5
    separations_to_check.append({
            'element_name': f'ip5:1',
            'plane': 'y',
            'varname': 'on_sep5',
            'scale_factor': -2*1e-3,
            'tol': tol[2]})
    # IP2 and IP8
    separations_to_check.append({
            'element_name': f'ip2:1',
            'plane': 'x',
            'varname': 'on_sep2',
            'scale_factor': -2*1e-3,
            'tol': tol[1]})

    separations_to_check.append({
            'element_name': f'ip8:1',
            'plane': 'y',
            'varname': 'on_sep8',
            'scale_factor': -2*1e-3,
            'tol': tol[3]})

    pm.check_separations_against_madvars(separations_to_check,
            twiss_df_b1, twiss_df_b2, variables_dict)

# From Guido: https://github.com/sterbini/run3_beta_beating
def create_bb_shedule_to_track(filling_scheme_fname,bunch_to_track, beam=1):
    import fillingpatterns as fp
    patt = fp.FillingPattern.from_json(filling_scheme_fname)
    patt.compute_beam_beam_schedule(n_lr_per_side=20)
    bb_shedule_to_track = patt[f'b{beam}'].bb_schedule.loc[bunch_to_track]
    return bb_shedule_to_track

def filter_bb_df(bb_df, bb_schedule_to_track):
    import pandas as pd
    if bb_schedule_to_track['collides in ATLAS/CMS']==False:
        bb_df=bb_df[~((bb_df['ip_name']=='ip1') & (bb_df['label']=='bb_ho'))]
        bb_df=bb_df[~((bb_df['ip_name']=='ip5') & (bb_df['label']=='bb_ho'))]
    if bb_schedule_to_track['collides in LHCB']==False:
        bb_df=bb_df[~((bb_df['ip_name']=='ip8') & (bb_df['label']=='bb_ho'))]
    if bb_schedule_to_track['collides in ALICE']==False:
        bb_df=bb_df[~((bb_df['ip_name']=='ip2') & (bb_df['label']=='bb_ho'))]

    bb_df_ho=bb_df[bb_df['label']=='bb_ho'].copy()

    # BBLR ATLAS
    lr_ATLAS=bb_df[(bb_df['ip_name']=='ip1') & (bb_df['label']=='bb_lr')].copy()
    lr_ATLAS=lr_ATLAS[lr_ATLAS['identifier'].apply(lambda x: x in bb_schedule_to_track['Positions in ATLAS/CMS'])]

    # BBLR ALICE
    lr_ALICE=bb_df[(bb_df['ip_name']=='ip2') & (bb_df['label']=='bb_lr')].copy()
    lr_ALICE=lr_ALICE[lr_ALICE['identifier'].apply(lambda x: x in bb_schedule_to_track['Positions in ALICE'])]

    # BBLR CMS
    lr_CMS=bb_df[(bb_df['ip_name']=='ip5') & (bb_df['label']=='bb_lr')].copy()
    lr_CMS=lr_CMS[lr_CMS['identifier'].apply(lambda x: x in bb_schedule_to_track['Positions in ATLAS/CMS'])]

    # BBLR LHCB
    lr_LHCB=bb_df[(bb_df['ip_name']=='ip8') & (bb_df['label']=='bb_lr')].copy()
    lr_LHCB=lr_LHCB[lr_LHCB['identifier'].apply(lambda x: x in bb_schedule_to_track['Positions in LHCB'])]

    aux=pd.concat([bb_df_ho, lr_ATLAS, lr_ALICE, lr_CMS, lr_LHCB])
    return aux
