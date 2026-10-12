# Controls research: games and wheels (2026-10-12)

Research-only guidance behind Setup › Controls ([../controls.md](../controls.md)). Nothing here is validated on the
owner's rig; only the F1 25 live button test (`BUTN` / UDP Action) can check a button in the app, and only the owner's
live run of the validation kit (`wheel_buttons`) counts as evidence. Text below is written in Pitwall's words; the
research files hold the verbatim game action names (`native_name`), each with its sources.

Files (the package keeps byte-identical copies, checked by `tests/unit/test_controls_catalog.py`):

- [controls-games.json](controls-games.json): 30 function ids, 11 games, 142 rows (in race or not, binding type,
  pad and wheel defaults where published, telemetry, evidence, sources), the owner's questions.
- [controls-wheels.json](controls-wheels.json): the four-layer wheel model, 23 brand templates plus "custom", platform
  rules, console limits, what Pitwall can see.
- `src/pitwall/controls/data/controls_pitwall.json`: Pitwall's normalisation of both, all design choices [D].

Evidence in the research: games use `official`, `official+community`, `community`, `not_found` (mapped to V, A, U and
no letter); wheels use V (read in an official document), A (inferred from official figures or tables), U
(community, retailer or press, or not checked) and D (Pitwall's derivation).

## Games

- **F1 25 (incl. the 2026 Season Pack)**: bindings from EA's controls hubs (pad, wheel, MFD shortcuts, UDP custom
  actions) [official]. DRS/S Mode and Pit Limiter share one button by default (pit lane versus track). Brake bias,
  differential, fuel mix and ERS mode are MFD shortcuts, unassigned on the pad. Traction control and ABS are assists
  set in the menu. Wing and ride height are setup items. UDP Action 1-12 are the only way Pitwall sees a wheel button
  (`BUTN`). EA lists the GT DD Pro among wheels with bindings in place but publishes only the Logitech G923 example.
- **Gran Turismo 7**: the official manual names the MFD pages (TCS, brake balance, fuel map, torque split) and the
  assists; ASM and ABS are pause-menu settings, not on the MFD and not bindable. Pad defaults are community. The GT DD
  Pro's four coloured sticks are assigned by the game itself (Fanatec, official); which colour does what is
  community-reported. No pit limiter button: the game takes over in the pit lane.
- **Assetto Corsa**: PC binding names (community, from the Custom Shaders Patch list); the console binding list was
  not found, so console rows are unverified.
- **ACC**: Kunos release notes (via news mirrors, labelled community here) and community `controls.json` names; TC,
  ABS and brake bias bindings exist; engine map on the MFD.
- **Forza Motorsport / Horizon**: assists in menus; Quick Actions on the D-pad [official].
- **iRacing**: official keyboard template plus community action names; most car controls are car-dependent.
- **Le Mans Ultimate, rFactor 2, Automobilista 2, RaceRoom, AC EVO**: controls-only games (Pitwall reads no telemetry
  from them). LMU from its official guide plus community names; rF2's onboard TC/ABS maps from Studio 397's docs;
  AMS2 and AC EVO names from installed files (community); RaceRoom bindings not found (its telemetry header lists the
  settings).

Owner's questions, answered in the research: aero while driving (F1 25 S Mode/DRS only; elsewhere DRS on cars that
have it; wing angles setup only), ride height (no game), stability (GT7 ASM pause menu only; F1 25 none; AC EVO and
AMS2 have bindings [community]), ABS and TC (see each game), push-to-talk on any wheel (F1 25 only; elsewhere the
iPad's button), current value after a change (F1 25 brake bias and ERS mode).

## Wheels

Templates with a control table (controls plus per-platform signals): Fanatec GT DD Pro wheel (positions from the
manual figure and Fanatec's video, see [gt-dd-pro-ps5-walkthrough.md](gt-dd-pro-ps5-walkthrough.md)), CSL Elite
McLaren GT3 V2, ClubSport Formula V2.5 / V2.5 X, CSL P1 V2, ClubSport F1 Esports V2, Podium Button Module Rally,
Logitech G923 (PS and Xbox), PRO Racing Wheel (Xbox), RS Wheel Hub, Thrustmaster T248 / T248X, T-GT II and the SF1000
add-on. Counts only (numbers of each kind, placed by the driver): CSL Elite WRC, TS-PC Racer, MOZA ES/ESX, CS V2P,
GS V2P, KS, FSR2, Simagic GT NEO, Simucube Tahko GT-21, Cammus C12.

Positions: from the makers' mapping figures for the Fanatec McLaren GT3 V2, Formula V2.5 X, P1 V2 and F1 Esports V2
(inferred), from the walkthrough for the GT DD Pro; other templates leave controls "Not placed yet" (shift and
analogue paddles behind the wheel).

Platform facts used by the suggestions:

- The GT DD Pro wheel is not Xbox-licensed (inferred); its two hub buttons look like Create and Options (inferred from
  shape, not named by Fanatec), kept as console buttons.
- McLaren GT3 V2 on Xbox: the rotary switches send nothing and both encoders send LT/RT (Fanatec's table).
- Fanatec rotary switches step + and - only in ENC mode; PULSE/CONST send one button per position.
- Logitech G923 (PS): L3, R3, + and - need games that support them (Logitech's guide).
- Thrustmaster T248 on PS: the encoders work only in games that support Thrustmaster encoders; on Xbox they become
  D-pad presses.
- F1 Esports V2 on PS: three controls send Cross, so neither the game nor `BUTN` can tell them apart.
- PC games that read only 32 buttons miss Fanatec rotary positions 37-76 and the Rally module's 99/100.

Still unverified: which GT DD Pro control sets which `BUTN` bit; whether a coloured stick bound to a UDP Action
reaches F1 25; what the paddles and hub buttons send; whether F1 25 drops or swaps an action when a used button is
rebound; whether `BUTN` reflects raw wheel inputs regardless of bindings; which way "Brake Bias Increase" moves the
bias (learned per layout by the test).

## Licences and copying

Names and facts only, in Pitwall's words. GPL sources (the rFactor 2 internals header copy in a GPL-3.0 repository, the
AC EVO shared-memory structs) and the unlicensed X2 file were read for names and facts; no code was copied. Simucube's
sc-api (MIT) role vocabulary, irdashies and pyirsdk (MIT) are used for names. See [../licences.md](../licences.md).

## Sources

`community` marks community, retailer, press or third-party mirror sources; `internal` points into this repository.

| Key | Kind | Source |
|---|---|---|
| `ea26_pad_ps` | official | https://www.ea.com/games/f1/f1-25/26-season-update-controls-hub/26-season-update-driving-controls-controller-playstation |
| `ea26_wheel_ps` | official | https://www.ea.com/games/f1/f1-25/26-season-update-controls-hub/26-season-update-driving-controls-wheel-playstation |
| `ea26_wheel_xbox` | official | https://www.ea.com/games/f1/f1-25/26-season-update-controls-hub/26-season-update-driving-controls-wheel-xbox |
| `ea26_wheel_pc` | official | https://www.ea.com/games/f1/f1-25/26-season-update-controls-hub/26-season-update-driving-controls-wheel-pc |
| `ea26_pad_xbox` | official | https://www.ea.com/games/f1/f1-25/26-season-update-controls-hub/26-season-update-driving-controls-controller-xbox |
| `ea26_kb_pc` | official | https://www.ea.com/games/f1/f1-25/26-season-update-controls-hub/26-season-update-driving-controls-keyboard-pc |
| `ea26_mfd_wheel_ps` | official | https://www.ea.com/games/f1/f1-25/26-season-update-controls-hub/26-season-update-mfd-shortcuts-wheel-playstation |
| `ea25_mfd_pad_ps` | official | https://www.ea.com/games/f1/f1-25/f1-25-controls-hub/mfd-shortcuts-controller-playstation |
| `ea25_mfd_wheel_xbox` | official | https://www.ea.com/games/f1/f1-25/f1-25-controls-hub/mfd-shortcuts-controls-wheel-xbox |
| `ea26_udp_wheel_ps` | official | https://www.ea.com/games/f1/f1-25/26-season-update-controls-hub/26-season-update-udp-custom-actions-wheel-playstation |
| `ea26_devices_ps` | official | https://www.ea.com/games/f1/f1-25/26-season-update-controls-hub/26-season-update-supported-devices-playstation |
| `ea26_devices_pc` | official | https://www.ea.com/games/f1/f1-25/26-season-update-controls-hub/26-season-update-supported-devices-pc |
| `ea_tips_2026` | official | https://www.ea.com/games/f1/f1-25/news/f1-25-2026-season-pack-tips-and-tricks |
| `ea_patch_120` | official | https://www.ea.com/games/f1/f1-25/news/f1-25-2026-season-pack-patch-notes-v120 |
| `ea_f122_able` | official | https://www.ea.com/able/resources/f1-22/pc/controls |
| `repo_f1_spec` | internal | docs/research/f1-udp-spec.md (EA Data Output spec PDFs, 2025 v3 and 2026 v1.2) |
| `fan_f1_25` | official | https://www.fanatec.com/uk/en/explorer/games/f1-2024/how-to-configure-your-racing-wheel-for-f1-25/ |
| `gt7m_mfd` | official | https://www.gran-turismo.com/gb/gt7/manual/race/04 |
| `gt7m_assist` | official | https://www.gran-turismo.com/gb/gt7/manual/drivingoption/03 |
| `gt7m_pause` | official | https://www.gran-turismo.com/gb/gt7/manual/race/05 |
| `gt7m_screen` | official | https://www.gran-turismo.com/gb/gt7/manual/race/02 |
| `gt7m_pit` | official | https://www.gran-turismo.com/gb/gt7/manual/race/07 |
| `gt7m_views` | official | https://www.gran-turismo.com/gb/gt7/manual/race/03 |
| `gt7m_options` | official | https://www.gran-turismo.com/gb/gt7/manual/option/01 |
| `gt7m_wheels` | official | https://www.gran-turismo.com/gb/gt7/manual/controller/02 |
| `gt7m_carsettings` | official | https://www.gran-turismo.com/gb/gt7/manual/drivingoption/02 |
| `fan_pvgt_gt7` | official | https://www.fanatec.com/uk/en/explorer/products/steering-wheel/using-the-csl-elite-steering-wheel-porsche-vision-gt-in-gran-turismo-7/ |
| `fan_forum_gt7_extra` | community | https://forum.fanatec.com/discussion/28493/gran-turismo-7-extra-buttons-mapping |
| `og_gt7_pad` | community | https://outsidergaming.com/gran-turismo-7-controls-guide-for-ps4-ps5-and-gameplay-tips-for-beginners/ |
| `repo_gt7` | internal | docs/research/gt7-protocol.md section 4.1 (flags at 0x8E) |
| `csp_ac_controls` | community | https://github.com/ac-custom-shaders-patch/acc-extension-config/blob/master/config/data_controls_props.ini |
| `repo_ac_udp` | internal | docs/research/protocols/ac-remote-udp.md section 3.3 |
| `repo_ac_shm` | internal | docs/research/forza-ac-acc-iracing.md section 2.1 |
| `acc_r7` | community | https://www.gtplanet.net/forum/threads/assetto-corsa-competizione-early-access-release-7-is-out.386589/ |
| `acc_107` | community | https://www.gtplanet.net/forum/threads/assetto-corsa-competizione-update-1-0-7-new-tire-model-mid-session-saving-and-more.389137/ |
| `acc_152` | community | https://www.onlineracedriver.com/2020/07/28/assetto-corsa-competizione-update-v1-5-2-released |
| `repo_acc_shm` | internal | docs/research/forza-ac-acc-iracing.md sections 3.1 and 3.3 |
| `fm_access` | official | https://support.forza.net/hc/en-us/articles/46524064744851-Forza-Motorsport-Accessibility-Support |
| `fm_wheel` | official | https://support.forza.net/hc/en-us/articles/21423900676371-Forza-Motorsport-Advanced-Wheel-Tuning |
| `fm7_ctrl` | official | https://support.forza.net/hc/en-us/articles/360005421793-FM7-Controller-Settings |
| `fh5_wheel` | official | https://support.forza.net/hc/en-us/articles/4409761195923-FH5-Wheel-Setup-and-Tuning |
| `repo_forza` | internal | docs/research/forza-ac-acc-iracing.md section 1 |
| `ir_keys` | official | https://www.iracing.com/keyboard-shortcuts/ |
| `ir_limiter` | official | https://support.iracing.com/support/solutions/articles/31000166946-pit-speed-limiters |
| `pyirsdk_vars` | community | https://github.com/kutu/pyirsdk/blob/master/vars.txt |
| `irdashies_cs` | community | https://github.com/tariknz/irdashies/blob/main/src/types/carSystems.ts |
| `lmu_tc` | official | https://guide.lemansultimate.com/hc/en-gb/articles/13182869047311-How-do-I-configure-my-traction-control-in-Le-Mans-Ultimate |
| `lmu_bind` | official | https://guide.lemansultimate.com/hc/en-gb/articles/13182838936975-How-do-I-assign-buttons-in-Le-Mans-Ultimate |
| `lmu_mfd` | official | https://guide.lemansultimate.com/hc/en-gb/articles/13202210967055-Understanding-the-MFD-Multi-Function-Display |
| `lmu_assists` | official | https://guide.lemansultimate.com/hc/en-gb/articles/13162741614607-Driving-Assists |
| `lmu_wheel` | official | https://guide.lemansultimate.com/hc/en-gb/articles/13152295737359-How-to-set-up-your-wheel-and-pedals |
| `lmu_hyper` | official | https://guide.lemansultimate.com/hc/en-gb/articles/13152322265231-Hypercar-Category-LMH-LMDh |
| `lmu_abs` | official | https://guide.lemansultimate.com/hc/en-gb/articles/13211078435983-ABS-Anti-Lock-Braking-System-for-LMGT3-Cars |
| `lmu_v12` | official | https://guide.lemansultimate.com/hc/en-gb/articles/14556121957775-V1-2-Update-2 |
| `irdashies_lmu` | community | https://github.com/tariknz/irdashies/blob/main/src/app/lmu/mapTelemetry.ts |
| `s397_tcabs` | official | https://docs.studio-397.com/x/D4CB |
| `rf2_internals` | community | https://github.com/TheIronWolfModding/rF2SharedMemoryMapPlugin/blob/master/Include/InternalsPlugin.hpp (Studio 397 header copy inside a GPL-3.0 repo: facts only, do not copy) |
| `repo_pcars2` | internal | docs/research/protocols/pcars2-udp.md (sCarFlags, sBrakeBias) |
| `ams2_wiki` | community | https://automobilista2.wiki.gg/wiki/Features |
| `asetek_ams2` | official | https://www.asetek.com/simsports/wp-content/uploads/2024/05/Input-Guide-Automobilista-2.pdf |
| `r3e_h` | official | https://github.com/sector3studios/r3e-api/blob/master/sample-c/src/r3e.h |
| `simucube_roles` | official | https://github.com/Simucube/sc-api/blob/master/data/device_info_enums.json |
| `simrace_config` | community | https://github.com/dillonkirsch/simrace_config/blob/main/src/sim_controls_manager/control_names.py |
| `acevo_structs` | community | https://github.com/vazhure/vAzhureRacingHub/blob/main/KunosPlugin/ACEVO_Structs.cs (GPL-3.0: field names only, do not copy) |
| `fan_buttons` | official | https://www.fanatec.com/uk/en/explorer/products/steering-wheel/what-can-i-use-the-buttons-on-my-sim-racing-steering-wheel-for/ |
| `fan_gt_racing` | official | https://www.fanatec.com/uk/en/explorer/games/gaming-tips/configure-your-steering-wheel-for-gt-racing/ |
| `FAN-PLAT` | official | Fanatec, Platform compatibility explained - https://www.fanatec.com/us/en/s/platform-compatibility |
| `FAN-PSFAQ` | official | Fanatec help, PlayStation Compatibility FAQ (updated 2026-07-30) - https://help.fanatec.com/hc/en-us/articles/49324482078481-PlayStation-Compatibility-FAQ |
| `FAN-GTDDP-PROD` | official | Fanatec GT DD Pro 5 Nm QR2L bundle page (features, compatibility) - https://www.fanatec.com/eu/en/p/sim-racing-bundles/crd-9020007-eu/gran-turismo-dd-pro-5nm-qr2l-eu |
| `FAN-GTDDP-MAN` | official | GT DD Pro manual EN Rev.04 (p19 5.6) and Explorer manual (MPS/AP definitions) - https://www.fanatec.com/us/en/explorer/products/racing-wheels-wheel-bases/gran-turismo-dd-pro/ |
| `FAN-MCL` | official | Fanatec Explorer, CSL Elite Steering Wheel McLaren GT3 V2 quick guide - https://www.fanatec.com/eu/en/explorer/products/steering-wheel/csl-elite-steering-wheel-mclaren-qr2-lite/ |
| `FAN-FV25` | official | Fanatec Explorer, ClubSport Steering Wheel Formula V2.5 manual - https://www.fanatec.com/us/en/explorer/products/steering-wheel/wheel-cs-f-v25-qr-2/ |
| `FAN-FV25X` | official | Fanatec Explorer, ClubSport Steering Wheel Formula V2.5 X manual - https://www.fanatec.com/us/en/explorer/products/steering-wheel/wheel-cs-f-v25x-qr-2/ |
| `FAN-P1V2` | official | Fanatec Explorer, CSL Steering Wheel P1 V2 quick guide - https://www.fanatec.com/eu/en/explorer/products/steering-wheel/csl-sw-p1-v2/ |
| `FAN-WRC` | official | Fanatec Explorer, CSL Elite Steering Wheel WRC quick guide - https://www.fanatec.com/eu/en/explorer/products/steering-wheel/csl-e-sw-wrc-qr2l/ |
| `FAN-F1V2` | official | Fanatec Explorer, ClubSport Steering Wheel F1 Esports V2 quick guide - https://www.fanatec.com/eu/en/explorer/products/steering-wheel/clubsport-steering-wheel-f1-esports-v2-qr2-wheel-side/ |
| `FAN-PBMR` | official | Fanatec Explorer, Podium Button Module Rally quick guide - https://www.fanatec.com/eu/en/explorer/products/steering-wheel/p-bm-r/ |
| `FAN-ENC` | official | Fanatec Explorer, Using Rotary Encoders on your Fanatec Steering Wheel - https://www.fanatec.com/us/en/explorer/products/steering-wheel/rotary-encoders-on-fanatec-steering-wheel/ |
| `WALKTHROUGH` | internal | pitwall docs/research/gt-dd-pro-ps5-walkthrough.md section 1 - docs/research/gt-dd-pro-ps5-walkthrough.md |
| `LOG-G923PS` | official | Logitech G923 PS5/PS4 setup guide p6 - https://www.logitech.com/assets/66156/3/g923-trueforce-racing-wheel-ps5-qsg.pdf |
| `LOG-G923XB` | official | Logitech G923 Xbox One/PC setup guide p6 - https://www.logitech.com/assets/65932/2/g923-racing-wheel-qsg.pdf |
| `LOG-PROXB` | official | Logitech PRO Racing Wheel Xbox/PC setup guide p7-8, 14, 17 - https://www.logitech.com/assets/70072/3/pro_racing_wheel_for_xb_&_pc_web_qsg_samr.pdf |
| `LOG-RSHUB` | official | Logitech RS Wheel Hub setup guide p3-8 - https://www.logitech.com/assets/70193/2/rs_wheel_hub_web_qsg_emea.pdf |
| `LOG-RS50PS` | official | Logitech RS50 System/Base PS and PC setup guide p7-9 - https://www.logitech.com/content/dam/support/simulation/rs50/rs50-ps-and-pc-setup-guide-amr.pdf |
| `TM-T248PS` | official | Thrustmaster T248 (PS) user manual p2, p13 - https://ts.thrustmaster.com/download/accessories/Manuals/T248/T248PS_User_manual.pdf |
| `TM-T248X` | official | Thrustmaster T248X user manual p2, p13-14 and generic mapping - https://ts.thrustmaster.com/download/accessories/Manuals/T248/T248X_User_manual.pdf |
| `TM-TGT2` | official | Thrustmaster T-GT II user manual p2, p11 and generic mapping - https://ts.thrustmaster.com/download/pictures/PCMAC/TGT_II/T-GT_II_Mapping.pdf |
| `TM-SF1000` | official | Thrustmaster Formula Wheel Add-On Ferrari SF1000 user manual p9-11 and button mapping - https://ts.thrustmaster.com/download/pictures/PCMAC/SF1000/Ferrari_SF1000_button_mapping.pdf |
| `TM-TSPC` | official | Thrustmaster TS-PC Racer user manual p2, compatible wheels list - https://ts.thrustmaster.com/download/accessories/Manuals/TSPCRacer/TSPCRacer_User_Manual.pdf |
| `MOZA-BASEFAQ` | official | MOZA support, Wheel Base FAQs - https://support.mozaracing.com/support/solutions/articles/70000627811-wheel-base-faqs |
| `MOZA-XBFAQ` | official | MOZA support, Xbox FAQ - https://support.mozaracing.com/en/support/solutions/articles/70000663979-xbox-faq |
| `MOZA-ESX` | official | MOZA ESX steering wheel product page - https://mozaracing.com/products/esx-steering-wheel |
| `MOZA-KS` | official | MOZA KS steering wheel product page - https://mozaracing.com/products/ks-gt-wheel |
| `MOZA-CSV2P` | official | MOZA CS V2P product page - https://mozaracing.com/products/cs-v2p-wheel |
| `MOZA-GSV2P` | official | MOZA GS V2P product page - https://mozaracing.com/products/gs-v2p-gt-wheel |
| `MOZA-FSR2` | official | MOZA FSR2 product page - https://mozaracing.com/products/fsr2-formula-wheel |
| `MOZA-TGS26` | official | MOZA news, PS5 racing wheels at TGS 2026 - https://mozaracing.com/blogs/news/moza-tgs-2026 |
| `SC-REMAP` | official | Simucube docs, Tuner steering wheel input button remap - https://docs.simucube.com/TunerSoftware/steeringwheel/inputbuttonremap.html |
| `SC-TAHKO` | official | Simucube docs, Tahko wheels - https://docs.simucube.com/Wheels/Tahko/Tahko.html |
| `SIMAGIC-GTNEO` | official | Simagic GT NEO user manual - https://image.simagic.com/profile/upload/2024/05/15/SIMAGIC_GTNEO_UM.pdf |
| `ASETEK-XBOX` | official | Asetek press release, SimSports partnership with Xbox - https://www.asetek.com/press-releases/asetek-simsports-announces-partnership-with-xbox/ |
| `MS-RWB` | official | Microsoft Learn, RacingWheelButtons (Windows.Gaming.Input) - https://learn.microsoft.com/en-us/uwp/api/windows.gaming.input.racingwheelbuttons |
| `MS-GIRWB` | official | Microsoft Learn, GameInputRacingWheelButtons (GDK) - https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/input/gameinput/enums/gameinputracingwheelbuttons |
| `MS-DIJS2` | official | Microsoft Learn, DIJOYSTATE2 - https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ee416628(v=vs.85) |
| `MS-JOYINFOEX` | official | Microsoft Learn, JOYINFOEX - https://learn.microsoft.com/en-us/windows/win32/api/joystickapi/ns-joystickapi-joyinfoex |
| `EA-F1` | internal | EA F1 25 UDP spec (pitwall copy): Event BUTN, Appendix 8.9, Participants m_platform - docs/research/f1-udp-spec.md |
| `SRCH-F1V2-SPECS` | official | Fanatec F1 Esports V2 listing (11 buttons, 7-way FunkySwitch, analogue joystick), via search extract - https://fanatec.com/eu-en/clubsport-steering-wheel-f1-esports-v2 |
| `COMM-FAN-GTSTICKS` | community | Fanatec forum threads on GT DD Pro coloured sticks (community) - https://forum.fanatec.com/discussion/comment/96212 |
| `COMM-SC32` | community | Simucube community: oldest games read only the first 32 buttons (community) - https://community.granitedevices.com/t/simbin-games-and-simucube-2/7851 |
| `COMM-CAMMUS` | community | OverTake, Cammus C12 article (community/press) and retailer FAQs - https://overtake.gg/news/comments/78515 |
