import os

import numpy as np

#from cpymad.madx import Madx
from madxp import Madxp as Madx
import pymasktools as pmt
import optics_specific_tools as ost

# TODO:
# - Crabs
# - Some twiss savings and testing
# - Handle generation of sixtrack input correctly (legacy will be different)
# - Sort out test_submodule inconsistency

# Select mode
#mode = 'b1_without_bb'
mode = 'b1_with_bb'
#mode = 'b1_with_bb_legacy_macros'
#mode = 'b4_without_bb'
# mode = 'b4_from_b2_without_bb'
#mode = 'b4_from_b2_with_bb'


# Tolarances for checks [ip1, ip2, ip5, ip8]
tol_beta = [1e-3, 10e-2, 1e-3, 1e-2]
tol_sep = [1e-6, 1e-6, 1e-6, 1e-6]

pmt.make_links(force=True, links_dict={
    'tracking_tools': '/afs/cern.ch/eng/tracking-tools',
    'modules': 'tracking_tools/modules',
    'tools': 'tracking_tools/tools',
    'beambeam_macros': 'tracking_tools/beambeam_macros',
    'errors': 'tracking_tools/errors'})

optics_file = 'hl14_collision_optics.madx' #15 cm

check_betas_at_ips = True
check_separations_at_ips = True
save_intermediate_twiss = True

(beam_to_configure, sequences_to_check, sequence_to_track, generate_b4_from_b2,
    track_from_b4_mad_instance, enable_bb_python, enable_bb_legacy,
    force_disable_check_separations_at_ips,
    ) = pmt.get_pymask_configuration(mode)


if force_disable_check_separations_at_ips:
    check_separations_at_ips = False

mad = Madx()

# Build sequence
ost.build_sequence(mad, beam=beam_to_configure)

# Apply optics
ost.apply_optics(mad, optics_file=optics_file)

# Check and load parameters 
from parameters import parameters
pmt.checks_on_parameter_dict(parameters)

if not(enable_bb_legacy) and not(enable_bb_python):
    parameters['par_on_bb_switch'] = 0.

mad.set_variables_from_dict(params=parameters)

# Prepare sequences and attach beam
mad.call("modules/submodule_01a_preparation.madx")
mad.call("modules/submodule_01b_beam.madx")

# Test machine before any change
twiss_dfs, other_data = ost.twiss_and_check(mad, sequences_to_check,
        tol_beta=tol_beta, tol_sep=tol_sep,
        twiss_fname='twiss_from_optics',
        save_twiss_files=save_intermediate_twiss,
        check_betas_at_ips=check_betas_at_ips, check_separations_at_ips=check_separations_at_ips)

# Set phase, apply and save crossing
mad.call("modules/submodule_01c_phase.madx")
mad.call("modules/submodule_01d_crossing.madx")
mad.call("modules/submodule_01e_test.madx")
mad.call("modules/submodule_01f_use.madx")

# Test flat machine
mad.input('exec, crossing_disable')
twiss_dfs, other_data = ost.twiss_and_check(mad, sequences_to_check,
        tol_beta=tol_beta, tol_sep=tol_sep,
        twiss_fname='twiss_no_crossing',
        save_twiss_files=save_intermediate_twiss,
        check_betas_at_ips=check_betas_at_ips, check_separations_at_ips=check_separations_at_ips)
# Check flatness
flat_tol = 1e-6
for ss in twiss_dfs.keys():
    tt = twiss_dfs[ss]
    assert np.max(np.abs(tt.x)) < flat_tol
    assert np.max(np.abs(tt.y)) < flat_tol

# Check machine after crossing restore
mad.input('exec, crossing_restore')
twiss_dfs, other_data = ost.twiss_and_check(mad, sequences_to_check,
        tol_beta=tol_beta, tol_sep=tol_sep,
        twiss_fname='twiss_with_crossing',
        save_twiss_files=save_intermediate_twiss,
        check_betas_at_ips=check_betas_at_ips, check_separations_at_ips=check_separations_at_ips)

# Call leveling module
mad.use(f'lhcb{beam_to_configure}')
mad.call("modules/module_02_lumilevel.madx")

# Generate b4
if generate_b4_from_b2:
    mad_b2 = mad
    mad_b4 = Madx()
    ost.build_sequence(mad_b4, beam=4)
    ost.apply_optics(mad_b4, optics_file=optics_file)
    pmt.configure_b4_from_b2(mad_b4, mad_b2)

    twiss_dfs_b2, other_data_b2 = ost.twiss_and_check(mad_b2,
            sequences_to_check=['lhcb2'],
            tol_beta=tol_beta, tol_sep=tol_sep,
            twiss_fname='twiss_b2_for_b4check',
            save_twiss_files=save_intermediate_twiss,
            check_betas_at_ips=check_betas_at_ips, check_separations_at_ips=False)

    twiss_dfs_b4, other_data_b4 = ost.twiss_and_check(mad_b4,
            sequences_to_check=['lhcb2'],
            tol_beta=tol_beta, tol_sep=tol_sep,
            twiss_fname='twiss_b4_for_b4check',
            save_twiss_files=save_intermediate_twiss,
            check_betas_at_ips=check_betas_at_ips, check_separations_at_ips=False)



# Prepare bb dataframes
if enable_bb_python:
    import beambeam as bb
    bb_dfs = bb.generate_bb_dataframes(mad,
        ip_names=['ip1', 'ip2', 'ip5', 'ip8'],
        harmonic_number=35640,
        numberOfLRPerIRSide=[0, 0, 0, 0],
        # numberOfLRPerIRSide=[25, 20, 25, 20],
        bunch_spacing_buckets=10,
        #numberOfHOSlices=11,
        numberOfHOSlices=1,
        bunch_population_ppb=None,
        sigmaz_m=None,
        remove_dummy_lenses=True)

# Here the datafremes can be edited, e.g. to set bbb intensity

# Select mad object
if track_from_b4_mad_instance:
    mad_track = mad_b4
else:
    mad_track = mad

mad_track.input('on_disp = 0;')

mad_track.input('''
!Record the nominal IP position and crossing angle
if(mylhcbeam==1) {use,  sequence=lhcb1;};
if(mylhcbeam>1) {use,  sequence=lhcb2;};
twiss;
xnom1=table(twiss,IP1,x);pxnom1=table(twiss,IP1,px);ynom1=table(twiss,IP1,y);pynom1=table(twiss,IP1,py);
xnom2=table(twiss,IP2,x);pxnom2=table(twiss,IP2,px);ynom2=table(twiss,IP2,y);pynom2=table(twiss,IP2,py);
xnom5=table(twiss,IP5,x);pxnom5=table(twiss,IP5,px);ynom5=table(twiss,IP5,y);pynom5=table(twiss,IP5,py);
xnom8=table(twiss,IP8,x);pxnom8=table(twiss,IP8,px);ynom8=table(twiss,IP8,y);pynom8=table(twiss,IP8,py);
value,xnom1,xnom2,xnom5,xnom8;
value,ynom1,ynom2,ynom5,ynom8;
value,pxnom1,pxnom2,pxnom5,pxnom8;
value,pynom1,pynom2,pynom5,pynom8;
''')

# Install bb lenses
if enable_bb_python:
    if track_from_b4_mad_instance:
        bb_df_track = bb_dfs['b4']
        assert(sequence_to_track=='lhcb2')
    else:
        bb_df_track = bb_dfs['b1']
        assert(sequence_to_track=='lhcb1')

    bb.install_lenses_in_sequence(mad_track, bb_df_track, sequence_to_track)

    # Disable bb
    mad_track.input('on_bb_switch := on_bb_charge')
    mad_track.globals.on_bb_charge = 0


# Legacy bb macros
if enable_bb_legacy:
    assert(beam_to_configure == 1)
    assert(not(track_from_b4_mad_instance))
    assert(not(enable_bb_python))
    mad_track.call("modules/module_03_beambeam.madx")


# Final use
mad_track.use(sequence_to_track)

# Temp
mad_track.twiss()
qx_no_bb = mad_track.table.summ.q1

mad_track.globals['on_bb_charge'] = 1
mad_track.twiss()
qx_bb = mad_track.table.summ.q1

print(f'Qx no bb: {qx_no_bb}')
print(f'Qx with bb: {qx_bb}')

prrr

# # Install and correct errors
# mad_track.call("modules/module_04_errors.madx")
# 
# # Machine tuning (enables bb)
# mad_track.call("modules/module_05_tuning.madx")

# # Generate sixtrack
# mad_track.call("modules/module_06_generate.madx")

