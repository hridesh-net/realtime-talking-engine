# Graph Report - interview-watcher  (2026-09-12)

## Corpus Check
- 342 files · ~414,295 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 3780 nodes · 8634 edges · 194 communities (173 shown, 21 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 395 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39
- Community 40
- Community 41
- Community 42
- Community 43
- Community 44
- Community 45
- Community 46
- Community 47
- Community 48
- Community 49
- Community 50
- Community 51
- Community 52
- Community 53
- Community 54
- Community 55
- Community 56
- Community 57
- Community 58
- Community 59
- Community 60
- Community 61
- Community 62
- Community 63
- Community 64
- Community 65
- Community 66
- Community 67
- Community 68
- Community 69
- Community 70
- Community 71
- Community 72
- Community 73
- Community 74
- Community 75
- Community 76
- Community 77
- Community 78
- Community 79
- Community 80
- Community 81
- Community 82
- Community 83
- Community 84
- Community 85
- Community 86
- Community 87
- Community 88
- Community 89
- Community 90
- Community 91
- Community 92
- Community 93
- Community 94
- Community 95
- Community 96
- Community 97
- Community 98
- Community 99
- Community 100
- Community 101
- Community 102
- Community 103
- Community 104
- Community 105
- Community 106
- Community 107
- Community 108
- Community 109
- Community 110
- Community 111
- Community 112
- Community 113
- Community 114
- Community 115
- Community 116
- Community 117
- Community 118
- Community 119
- Community 120
- Community 121
- Community 122
- Community 123
- Community 124
- Community 125
- Community 126
- Community 127
- Community 128
- Community 129
- Community 130
- Community 131
- Community 132
- Community 133
- Community 134
- Community 135
- Community 136
- Community 137
- Community 138
- Community 139
- Community 140
- Community 141
- Community 142
- Community 143
- Community 144
- Community 145
- Community 146
- Community 147
- Community 148
- Community 149
- Community 150
- Community 151
- Community 152
- Community 153
- Community 154
- Community 155
- Community 156
- Community 157
- Community 158
- Community 159
- Community 160
- Community 161
- Community 162
- Community 163
- Community 190
- Community 191
- Community 192

## God Nodes (most connected - your core abstractions)
1. `actor` - 76 edges
2. `build_report()` - 73 edges
3. `ModelError` - 72 edges
4. `SignalResult` - 68 edges
5. `InterviewRepository` - 65 edges
6. `Context` - 49 edges
7. `get()` - 47 edges
8. `StructuredModel` - 39 edges
9. `VirtualCandidateAgent` - 36 edges
10. `Conn` - 35 edges

## Surprising Connections (you probably didn't know these)
- `Current Voice Fidelity Gap` --semantically_similar_to--> `Speaker-only Voice Limitation`  [INFERRED] [semantically similar]
  README.md → okf/concepts/contracts/realtime-voice.md
- `Control Plane Runtime Boundary` --semantically_similar_to--> `Go Engine Handoff`  [INFERRED] [semantically similar]
  okf/references/smart-interview-relationship.md → control_plane/README.md
- `AudioAnalysisAgent` --uses--> `AudioModel`  [INFERRED]
  analysis_agent/agent.py → llm/base.py
- `AudioAnalysisAgent` --uses--> `ModelError`  [INFERRED]
  analysis_agent/agent.py → llm/base.py
- `VirtualCandidateAgent` --uses--> `StructuredModel`  [INFERRED]
  candidate_agent/agent.py → llm/base.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Dual Cognition with Shared Memory** — docs_engine_implementation_plan_speaker, docs_engine_implementation_plan_thinker, docs_engine_implementation_plan_claims_ledger [EXTRACTED 1.00]
- **Current Voice and Evidence Side-channel Flow** — okf_concepts_contracts_realtime_voice_browser_vendor_media, okf_concepts_contracts_session_recording_browser_recording, okf_concepts_contracts_session_transcript_server_truth_transcript [EXTRACTED 1.00]
- **Human-like Realtime Engine Gap Cluster** — okf_concepts_contracts_realtime_voice_speaker_only_limitation, docs_engine_implementation_plan_deterministic_pregate, docs_engine_implementation_plan_stall_bank, docs_engine_implementation_plan_barge_in_draining, docs_engine_implementation_plan_claims_ledger, docs_engine_implementation_plan_async_ceiling_judge [INFERRED 0.95]
- **Browser-Direct Realtime Voice Flow** — okf_concepts_modules_candidate_agent_engine_contract_engine_contract, okf_concepts_modules_candidate_agent_voice_voice_session_compiler, okf_concepts_modules_control_plane_api_realtime_credential_mint, okf_concepts_subsystems_llm_port_realtime_broker, okf_concepts_subsystems_ui_browser_voice_runtime, okf_concepts_subsystems_llm_port_peer_to_vendor_media [EXTRACTED 1.00]
- **Dual-Model Human-Like Persona Control** — okf_concepts_subsystems_engine_speaker, okf_concepts_subsystems_engine_thinker, okf_concepts_subsystems_engine_claims_ledger, okf_concepts_subsystems_engine_deterministic_pregate, okf_concepts_subsystems_engine_stall_bank, okf_concepts_modules_candidate_agent_engine_contract_runtime_persona_fields [EXTRACTED 1.00]
- **Evaluation Evidence Pipeline** — okf_concepts_modules_candidate_agent_voice_bilateral_transcription, okf_concepts_subsystems_ui_dual_channel_browser_recording, okf_concepts_modules_control_plane_api_recording_chunk_upload, okf_concepts_modules_control_plane_api_transcript_append, analysis_agent_instructions_audio_analysis_contract, okf_concepts_subsystems_engine_unwired_judge [INFERRED 0.85]
- **Dual-model Shared-memory Conversation Loop** — docs_live_talking_engine_harness_speaker, docs_live_talking_engine_harness_thinker, docs_live_talking_engine_harness_harness_context, docs_live_talking_engine_harness_turns_and_rounds [EXTRACTED 1.00]
- **Deterministic Realtime Turn-control Path** — docs_engine_implementation_plan_session_actor, docs_engine_implementation_plan_state_machine, docs_engine_implementation_plan_deterministic_pregate, docs_engine_implementation_plan_stall_bank, docs_engine_implementation_plan_playout_tracker, docs_engine_implementation_plan_barge_in [EXTRACTED 1.00]
- **Gradable Session Ground-truth Pipeline** — docs_engine_implementation_plan_stereo_recorder, docs_engine_implementation_plan_s3_bundle, docs_engine_implementation_plan_control_plane_ingest, docs_engine_implementation_plan_judge_port, docs_engine_implementation_plan_observability [EXTRACTED 1.00]

## Communities (194 total, 21 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.04
Nodes (63): Candidate Session Agent — one persona turn in a live text interview. Stateless…, generate(), _judged(), Assemble a report-engine bundle from stored rows, and generate the report.…, Build the bundle, run the engine, and return the report as plain JSON. The…, Run the judge over a scored report, or hand back the one code composed., Draft the role-fact checklist statements for one job description., Turns a job description into statements for the fixed fact checklist. The… (+55 more)

### Community 1 - "Community 1"
Cohesion: 0.04
Nodes (86): _aptitude(), derive_traits(), Pick trait scores inside the archetype bounds. Deterministic in `seed`., get(), Look up one archetype, raising KeyError with the known keys listed., casting_realism_note(), jd_precis(), normalize_presented_gender() (+78 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (74): Random, Virtual Candidate Agent. Generates one persona per (interview, archetype). The…, _rng(), build_engine_contract(), compile_precompiled_beliefs(), compile_pregate_lexicon(), compile_stall_phrases(), _compile_system_prompt() (+66 more)

### Community 3 - "Community 3"
Cohesion: 0.04
Nodes (76): default_keys(), The two personas enrolled when the caller does not choose — select first., Read back the client-visible facts about a compiled session document. Shape-…, session_facts(), append_recording_chunk(), append_transcript_turn(), create_interview(), draft_role_facts() (+68 more)

### Community 4 - "Community 4"
Cohesion: 0.06
Nodes (50): jitterPacket, DefaultJitterConfig(), JitterBuffer, JitterConfig, JitterStats, NewJitterBuffer(), seqBefore(), jitterCfg() (+42 more)

### Community 5 - "Community 5"
Cohesion: 0.04
Nodes (71): The fixed manager rubric: criteria, weights and bands. **Org-owned…, _imported_roots(), _modules(), _parameter_annotations(), _pattern_alternatives(), parametrize, Path, Executable SOLID and layering checks (BRD NFR-003). Architecture rules rot… (+63 more)

### Community 6 - "Community 6"
Cohesion: 0.05
Nodes (64): _accent_directive(), _bullets(), _code_switch_directive(), _english(), Turn the accent number into something a speech model can act on., Turn the code-switch number into something a speech model can act on., Render the realism/compliance layer, if this persona carries one. Empty string…, A vocabulary key rendered for a reader: `30_days` -> `30 days`. Closed… (+56 more)

### Community 7 - "Community 7"
Cohesion: 0.05
Nodes (55): BaseException, ModelError, RuntimeError, Raised when a provider call fails or returns unusable output., _chain(), looks_like_a_key_failure(), Forget which key last worked. For tests, and for nothing else., The exception and everything it was raised from, innermost last. (+47 more)

### Community 8 - "Community 8"
Cohesion: 0.07
Nodes (62): persona_block(), The competency list this role should be scored against., The persona ground truth: what this candidate was hiding, and at what weight.…, role_family_for(), build_report(), Turn one session bundle into one report. Deterministic end to end. Args:…, _bundle(), The report engine's offline gate. The load-bearing test is determinism: re-… (+54 more)

### Community 9 - "Community 9"
Cohesion: 0.09
Nodes (52): rawListPackage, joinViolations(), loadGraph(), moduleRoot(), TestAdaptersOnlyImportPortsConfigObsAudioAndSharedVendorHelpers(), TestEnvAccessOnlyInConfig(), TestNoHardcodedModelIDLiteralsOutsideConfig(), TestNoPackageOutsideCmdEnginedImportsVendorTransportOrStore() (+44 more)

### Community 10 - "Community 10"
Cohesion: 0.09
Nodes (35): Config, loader, LookupFunc, Secret, stringListFlag, Load(), LoadFromEnv(), newStringListFlag() (+27 more)

### Community 11 - "Community 11"
Cohesion: 0.13
Nodes (12): clipPlayTime(), estimateSpeechDuration(), actor, context.Context, attachOutcome, command, commandKind, connectOutcome (+4 more)

### Community 12 - "Community 12"
Cohesion: 0.05
Nodes (34): get_realtime_broker(), Build the realtime-voice broker from environment configuration., Any, Analyse one span of audio, returning JSON matching `schema`. Implementations…, A short-lived secret a browser may use to open a realtime voice session.…, Mints per-session credentials for a vendor's realtime voice API. Not a third…, The realtime model identifier sessions are minted against., Short provider name, e.g. ``openai``. (+26 more)

### Community 13 - "Community 13"
Cohesion: 0.08
Nodes (46): wireContent, wirePart, New(), rateFromMime(), audioReply(), TestAnEmptyVoiceIsRefusedRatherThanDefaulted(), TestAnHTTPErrorCarriesTheVendorsExplanation(), TestAResponseWithNoAudioIsAnError() (+38 more)

### Community 14 - "Community 14"
Cohesion: 0.09
Nodes (50): apply(), bullets_for(), narrative_for(), out_of_four(), The sentences code can write from the measurements alone. A scorecard a manager…, The paragraph the report opens with., A 0-10 sub-score on the four-point scale the scorecard is read in. Presentation…, Write every composed sentence onto the report, in place. (+42 more)

### Community 15 - "Community 15"
Cohesion: 0.07
Nodes (19): Config, TestFakeTransport_AcceptAndMediaConn(), FakeMediaConn, FakeTransport, newFakeMediaConn(), NewFakeTransport(), ControlMessage, MediaConn (+11 more)

### Community 16 - "Community 16"
Cohesion: 0.07
Nodes (42): delete_candidate(), Remove a persona from an interview., AnalysisStore, AnalysisWorkflowStore, CandidateStore, EnrollmentStore, ExpectationStore, ExpectationWorkflowStore (+34 more)

### Community 17 - "Community 17"
Cohesion: 0.07
Nodes (25): TestFakeJudge_SubmitsAndReplaysVerdicts(), TestFakeSpeakerSession_Blocking(), TestFakeSpeakerSession_BlockingReleasedByContext(), TestFakeStallBank_CyclesAndWarms(), TestFakeStallBank_Empty(), NewFakeStallBank(), PCM16Audio, TTS (+17 more)

### Community 18 - "Community 18"
Cohesion: 0.08
Nodes (43): apply(), _clean(), JudgeModel, _must_discover(), _obj(), overlay(), prompt_for(), Any (+35 more)

### Community 19 - "Community 19"
Cohesion: 0.05
Nodes (46): Hinglish Verbatim Transcription, Stereo Speaker Attribution, Go Engine Handoff, EngineContract, Dual-Model Runtime Persona Fields, Bilateral Transcription, Deterministic Voice Identity, Hinglish Transcription Hole (+38 more)

### Community 20 - "Community 20"
Cohesion: 0.06
Nodes (42): check(), Turn, The language gate — spec section 3.4. BRD D-6: frontline interviews are…, Detect the manager's language mix and decide whether to gate the session. The…, Band, ChecklistItem, Criterion, JobCard (+34 more)

### Community 21 - "Community 21"
Cohesion: 0.08
Nodes (40): CompletedProcess, database_url(), A freshly migrated database, dropped when the session ends. The schema is built…, _container(), _container_ipv4(), create_database(), down(), drop_database() (+32 more)

### Community 22 - "Community 22"
Cohesion: 0.07
Nodes (33): get_repo(), Build the storage adapter that satisfies every port., init_db(), Path, Open or create the control-plane database and apply schema., InterviewRepository, _new_id(), Persist an expectation document for an interview. (+25 more)

### Community 23 - "Community 23"
Cohesion: 0.12
Nodes (36): NewFakeClock(), NewContractSource(), NewSampleContractSource(), TestFakeClock_DeterministicOrderAndCancel(), TestFakeClock_ResetDrainsUnreadFire(), TestFakeSpeaker_ScriptedConversation(), TestFakeThinker_NoteAndMiss(), TestSampleContractSource_ServesParsableContract() (+28 more)

### Community 24 - "Community 24"
Cohesion: 0.15
Nodes (32): SpeakerSession, Speaker, New(), newFakeVendor(), nextEvent(), quietLogger(), startSession(), TestAFullWriteQueueShedsAndSaysSoRatherThanWaiting() (+24 more)

### Community 25 - "Community 25"
Cohesion: 0.11
Nodes (40): The transcript as the veto reads it: an index from span to turn., Transcript, _all_surfaced(), _bundle(), _judged(), parametrize, The judge layer's gate — spec section 6. The deterministic engine is pinned by…, Rule 2: discovery is what the candidate revealed, not what the manager asked. (+32 more)

### Community 26 - "Community 26"
Cohesion: 0.08
Nodes (32): _arr(), AudioAnalysisAgent, _obj(), Any, Path, The audio analysis agent. One session's recording in, one `SessionAnalysis`…, Analyses a recording against the expectation it was held against., One window, analysed on its own clock. (+24 more)

### Community 27 - "Community 27"
Cohesion: 0.12
Nodes (32): NewFakeSpeaker(), pumpSpeakerEvents(), actor, newConnectRig(), TestASlowVendorStartIsBoundedByTheConnectTimeout(), TestATranscriberFailureDegradesTheSessionInsteadOfEndingIt(), TestAttachingATransportTwiceIsConflictNotASecondConnector(), TestAttachTransportWithNoSpeakerConfiguredWindsTheSessionDownSynchronously() (+24 more)

### Community 28 - "Community 28"
Cohesion: 0.07
Nodes (37): AnswerPolicySpec, TypedDict, Fixed speech settings an archetype contributes to every persona it casts., Fixed answer settings an archetype contributes to every persona it casts., SpeechSpec, EnvironmentProfile, Session-logistics realism — the 'Environment' row of the realism taxonomy., archetype_key() (+29 more)

### Community 29 - "Community 29"
Cohesion: 0.09
Nodes (8): FakeSpeakerSession, newFakeSpeakerSession(), ResponseDirectives, SessionCfg, SpeakerEvent, BlockMethod, FakeSpeaker, Truncation

### Community 30 - "Community 30"
Cohesion: 0.08
Nodes (30): get_session_agent(), Build the candidate session agent from environment configuration., client(), _enroll(), FakeCastingModel, FakeChatModel, interview_id(), Any (+22 more)

### Community 31 - "Community 31"
Cohesion: 0.09
Nodes (15): NoteScriptEntry, Note, PersonaCtx, buildPrompt(), clamp01(), cleanList(), Thinker, normalize() (+7 more)

### Community 32 - "Community 32"
Cohesion: 0.08
Nodes (26): BehavioralAssessment, EvaluationCriterion, InterviewerGuidance, InterviewPhase, BaseModel, One timed phase of the interview., How one skill must be assessed., Whether and how the resume must be probed. (+18 more)

### Community 33 - "Community 33"
Cohesion: 0.09
Nodes (30): _agenda_set(), _base(), _candidate_question_answer_rate(), _cue_signal(), _downside(), extract(), _fact_coverage(), _invite_fraction() (+22 more)

### Community 34 - "Community 34"
Cohesion: 0.08
Nodes (10): TestFakeTranscriber_ScriptedPartials(), TestFakeRecorder_RecordsAndFinalizes(), NewFakeRecorder(), NewFakeTranscriber(), RecordingInfo, Partial, Frame, FakeRecorder (+2 more)

### Community 35 - "Community 35"
Cohesion: 0.07
Nodes (33): Coaching, for_signal(), in_perspective(), Behaviour-level coaching lines for each signal. Kluger & DeNisi (1996, 607…, What went well or badly, and the sentence to rehearse., Coaching for a signal, with a safe fallback for anything unmapped., Rewrite a coaching line for its audience. Deliberately a small substitution…, Standalone manager-assessment report engine. One session bundle in, one report… (+25 more)

### Community 36 - "Community 36"
Cohesion: 0.14
Nodes (29): Judge, New(), fixtureServer(), floodQueue(), judgeServer(), loadFixture(), newJudge(), requireVerdict() (+21 more)

### Community 37 - "Community 37"
Cohesion: 0.11
Nodes (30): pumpMediaConn(), fireNext(), actor, newActorWithDeps(), TestABargeInDuringTheOpeningLineCancelsItsPlayoutAlarm(), TestANonYieldingPersonaHoldsTheFloorInEverySpeakingIshState(), TestAnUnhandledSpeakerEventIsRecordedRatherThanDropped(), TestAZeroCapIsNotArmedRatherThanFiringImmediately() (+22 more)

### Community 38 - "Community 38"
Cohesion: 0.11
Nodes (31): Question-act extraction and typing — spec section 3.2 and 3.3. Turns are too…, The first act of each topic — the questions probes hang off., root_questions(), _base(), _behavioural_share(), _closed_share(), _competency_coverage(), _cues_for() (+23 more)

### Community 39 - "Community 39"
Cohesion: 0.12
Nodes (28): One deterministic measurement and the score it transfers to., Whether this signal produced a score for this session., Drop repeated quotes. Two candidate questions answered in one manager turn are…, SignalResult, load_pack(), Any, Read a versioned pack from `report_engine/packs`., _accommodation() (+20 more)

### Community 40 - "Community 40"
Cohesion: 0.09
Nodes (30): _file(), parametrize, ranged(), One contract, two adapters — the object store's behaviour, held to both. Almost…, What went in comes back out — a filesystem has to record it too., A whole missing prefix is still just "no object", not an error., An object of known content, for the range cases below., Asking for more than there is returns what there is, in both adapters. S3… (+22 more)

### Community 41 - "Community 41"
Cohesion: 0.13
Nodes (28): AnalysisInput, Evidence, The audio analysis, as data. Mirrors what `analysis_agent` produces without…, A quoted transcript moment. Every claim in the report carries one., `mm:ss` on the session clock., _anchors(), _base(), _early_end() (+20 more)

### Community 42 - "Community 42"
Cohesion: 0.12
Nodes (28): _merge_delivery(), _merge_early_end(), Merging and validating what the model returns, window by window. Code owns…, Weight each window's delivery read by how much was said in it., The close happens once, in whichever window heard it., _shift(), AnalysedTurn, DeliveryObservation (+20 more)

### Community 43 - "Community 43"
Cohesion: 0.10
Nodes (27): database_url_from_env(), Postgres DSN from DATABASE_URL, falling back to the default., _applied(), assert_current(), _checksum(), database_url(), discover(), ensure_ledger() (+19 more)

### Community 44 - "Community 44"
Cohesion: 0.09
Nodes (23): CandidateSessionAgent, Any, ChatMessage, EngineContract, Plays a cast persona through a typed interview, one turn at a time., Model identifier, recorded against the session that used it., Return the persona's next line, given the transcript so far. Args: contract:…, Map the transcript onto chat roles, preserving order. (+15 more)

### Community 45 - "Community 45"
Cohesion: 0.15
Nodes (28): apply(), main(), Apply every pending migration in order; return the versions applied. Each file…, CLI entry point. Returns the process exit code., conn(), One connection out of the clean pool, returned to it afterwards., fresh_dsn(), migrations_copy() (+20 more)

### Community 46 - "Community 46"
Cohesion: 0.12
Nodes (27): Match, _base(), _compound_rate(), extract(), _greeting(), _longest_monologue(), _pace_advisory(), Communication & Presence signals — spec section 5.D. Talk share is measured in… (+19 more)

### Community 47 - "Community 47"
Cohesion: 0.16
Nodes (22): PregateSkill, TurnPolicy, UnlockSpec, VoiceDirectives, checkVersion(), EngineContract, Parse(), parseVersion() (+14 more)

### Community 48 - "Community 48"
Cohesion: 0.11
Nodes (24): _open_voice_session(), Path, Offline tests for session recordings — storage, sequencing, and endpoints. No…, Create an interview + persona through the repo, then open a voice session via…, The camera rides in the same recording, so the mime is whatever seq 0 said. The…, A `<video>` probes with a Range before it plays; a 200 makes it download it…, An analysis agent that records the path it was handed and calls no model., Analyse hands over the real recording; it used to copy it into /tmp and leak… (+16 more)

### Community 49 - "Community 49"
Cohesion: 0.09
Nodes (22): _fingerprint(), Any, Cast one persona for this interview and archetype. Args: interview_id:…, Every required skill present exactly once, clamped to the band., Weights come from the catalog; the model only re-words the signals., Delegate to the injected provider., Accept a stance only if it is one the schema allows., Coerce a model-supplied list to clean, bounded strings. The model can return… (+14 more)

### Community 50 - "Community 50"
Cohesion: 0.10
Nodes (23): list_sessions(), Every session held against one interview, newest first. Returns an empty list…, _fingerprint(), generate_persona(), Random, Deterministic persona generation from BRD §4.3 / §5.2., Generate a deterministic CandidatePersona per BRD FR-002., _rng() (+15 more)

### Community 51 - "Community 51"
Cohesion: 0.08
Nodes (15): ClaimLedger, PreGate, Recorder, AudioDelta, Speaker, StallBank, Thinker, Transcriber (+7 more)

### Community 52 - "Community 52"
Cohesion: 0.13
Nodes (21): TestAFrameWithNoDeclaredRateFallsBackRatherThanBeingDropped(), TestPlayoutMeasuresDurationSoMixedSampleRatesAreNotMisMeasured(), T, offerDrop(), offerNewest(), newPlayoutTracker(), canTransition(), pcmFor() (+13 more)

### Community 53 - "Community 53"
Cohesion: 0.16
Nodes (3): modelPath(), session, Speaker

### Community 54 - "Community 54"
Cohesion: 0.15
Nodes (23): plan(), `(offset_ms, duration_ms)` for each window. Pure, so it is testable., merge(), Fold per-window answers into one analysis on the recording's clock. `answers`…, The analysis agent's offline gate. Everything here runs without a model or an…, A late window's overshoot must not hide under earlier windows' headroom., And coverage is recomputed from the counts, not taken on the model's word., The case the design exists for: correct early close, little covered. (+15 more)

### Community 55 - "Community 55"
Cohesion: 0.11
Nodes (22): build_app(), cors_allowed_origins(), Origins allowed to call this service from a browser, from the environment.…, Construct the control-plane application., Regression: composed personas used to die on the next deploy. The archetype…, test_a_custom_persona_survives_a_process_restart(), _open_session(), Offline tests for what the SkillBrew portal needs from this API. The portal… (+14 more)

### Community 56 - "Community 56"
Cohesion: 0.25
Nodes (22): New(), newThinker(), noteServer(), TestALaterPartialSupersedesTheEarlierSpeculation(), TestAMissedDeadlineClosesTheChannelWithoutANote(), TestANoteArrivesBeforeTheDeadline(), TestAnUnlockAssessmentIsOnlyReportedWhenTheModelMadeOne(), TestAShortPartialIsNotWorthACall() (+14 more)

### Community 57 - "Community 57"
Cohesion: 0.12
Nodes (21): broker(), client(), _open_voice_session(), fixture, Offline tests for the voice session — compilation, credential minting, ingest.…, Cast time reads one tuple and session time the other; they are one object., Every voice is classified, exactly once, and nothing is classified twice. The…, The persona *says* it. Writing it here too would duplicate turn 0. (+13 more)

### Community 58 - "Community 58"
Cohesion: 0.16
Nodes (20): boundary(), containsPhrase(), Gate, less(), New(), sortEntries(), TestAContractWithNoLexiconNeverDefers(), TestALexiconEntryWithNoCeilingDoesNotDefer() (+12 more)

### Community 59 - "Community 59"
Cohesion: 0.10
Nodes (19): Any, Delegate to the injected provider., Generate one expectation document. Deterministic given same inputs., build_user_prompt(), System prompt and guardrails for the Interview Expectation Agent. Persona: a…, Render the expectation user prompt., determine_interview_type(), interviewer_guidance() (+11 more)

### Community 60 - "Community 60"
Cohesion: 0.12
Nodes (17): ClientError, _flag(), _is_not_found(), object_store_from_env(), Where a session's bytes come to rest — one port, two adapters. The control…, Reject a key that either adapter would have to interpret differently. A logical…, True when a `ClientError` is a 404 rather than something worse., S3, or anything that speaks it — MinIO in dev, a real bucket in prod.… (+9 more)

### Community 61 - "Community 61"
Cohesion: 0.12
Nodes (13): get_analysis_status(), State and provenance of this session's analysis., Mark analysis as running, replacing any previous attempt., Record that analysis failed, and why., State and provenance without the body., Upsert a persona. Re-enrolling an archetype replaces the old cast., Mark analysis as running, replacing any previous attempt. Replacing rather than…, Store a finished analysis. (+5 more)

### Community 62 - "Community 62"
Cohesion: 0.10
Nodes (13): Any, Store a finished analysis., The stored analysis body, or None when there is none., Store or replace this session's report. Returns its metadata., The stored report body, or None when none has been generated., The stored report's headline and provenance, without its body., Any, The stored analysis body, or None when there is none. (+5 more)

### Community 63 - "Community 63"
Cohesion: 0.17
Nodes (16): main(), run(), shutdown(), DefaultConfig(), Transport, mintTicket(), New(), quietLogger() (+8 more)

### Community 64 - "Community 64"
Cohesion: 0.19
Nodes (11): handleHealthz(), NewHandler(), net/http.Request, net/http.ResponseWriter, net/http.ServeMux, attachTransportRequest, attachTransportResponse, createRequest (+3 more)

### Community 65 - "Community 65"
Cohesion: 0.09
Nodes (21): @google/genai, react, react-dom, dependencies, @google/genai, react, react-dom, devDependencies (+13 more)

### Community 66 - "Community 66"
Cohesion: 0.11
Nodes (13): Model ID recorded against generated personas., Casts virtual candidates for interviewer-training sessions., VirtualCandidateAgent, get_candidate_agent(), get_expectation_agent(), Build the virtual candidate agent from environment configuration., Build the expectation agent from environment configuration., client() (+5 more)

### Community 67 - "Community 67"
Cohesion: 0.12
Nodes (21): build_realtime_session(), EngineContract, Compile the OpenAI Realtime session document for one persona. Args: contract:…, A transcription hint listing the skills this interview will name. Transcribers…, _vocabulary(), _contract(), A spoken session has no turn 0 to write it into, so the model is told., Hand-built contracts stay valid; the persona just greets as it would. (+13 more)

### Community 68 - "Community 68"
Cohesion: 0.20
Nodes (20): automaticActivityDetection, clientContentMsg, clientMessage, content, contextCompression, generationConfig, goAway, inlineData (+12 more)

### Community 69 - "Community 69"
Cohesion: 0.12
Nodes (11): Path, Append one chunk. `seq` must equal the recording's next expected seq., Mark the recording complete. Idempotent; None when there is none., Return the recording's metadata, or None when it does not exist., Return the recording's metadata and the file holding it, or None. A **path**,…, Append one chunk, enforcing `seq == next_seq` and disk-then-row order. Same…, Mark the recording complete. Idempotent; None when there is no recording., Return the recording's metadata, or None when it does not exist. (+3 more)

### Community 70 - "Community 70"
Cohesion: 0.12
Nodes (14): _client(), OpenAIChatModel, OpenAIModel, _parse(), Any, ChatMessage, Parse a JSON object response, rejecting anything that is not a dict., Reject an empty completion — a silent blank turn stalls the session. (+6 more)

### Community 71 - "Community 71"
Cohesion: 0.14
Nodes (15): draftRoleFacts(), listTraitDimensions(), EMPTY_PERSONA, hintText(), PERSONA_RADAR_DIMENSIONS, PersonaComposer(), personaRadarAxes(), personaSpecError() (+7 more)

### Community 72 - "Community 72"
Cohesion: 0.12
Nodes (12): get_session(), Fetch a session with its full timestamped transcript., Open a session, seeding turn 0 with the persona's opening line., Return one session with its full transcript, or None., Close a session. Returns the final record, or None when unknown., Turn, Open a session, seeding turn 0 with the persona's opening line. The opening…, Return one session with its full transcript, or None. (+4 more)

### Community 73 - "Community 73"
Cohesion: 0.18
Nodes (5): FakeClock, Timer, fakeTimer, PendingTimer, time.Duration

### Community 74 - "Community 74"
Cohesion: 0.13
Nodes (10): TestStore_PutAndGet(), NewFakeFinalizer(), TestFakeFinalizer_RecordsInput(), NewStore(), FinalizeInput, Finalizer, FakeFinalizer, Store (+2 more)

### Community 75 - "Community 75"
Cohesion: 0.16
Nodes (9): NewFakeJudge(), Judge, TurnForReview, Verdict, buildPrompt(), Judge, normalize(), FakeJudge (+1 more)

### Community 76 - "Community 76"
Cohesion: 0.22
Nodes (18): AbortedError, columns(), drop_column(), main(), migrate(), Connection, Exception, Path (+10 more)

### Community 77 - "Community 77"
Cohesion: 0.14
Nodes (16): Archetype, Fixed catalog of virtual-candidate archetypes. Code-defined and versioned. The…, One persona family: fixed verdict, fixed trait bounds, fixed scorecard., Trait bounds as JSON-serializable lists., Assert one archetype is well formed, whether or not it is ever registered.…, Validate and add to the process-wide catalog. Module import time only., One thing a competent interviewer must surface about this persona., _register() (+8 more)

### Community 78 - "Community 78"
Cohesion: 0.12
Nodes (12): list_interviews(), List interviews, newest first, optionally filtered by status., Persist a new interview and return the stored record., Return one interview, or None when it does not exist., Return interviews, newest first, optionally filtered by status., build_bundle(), Everything the engine needs for one session, as one validated object., Return one interview, or None when it does not exist. (+4 more)

### Community 79 - "Community 79"
Cohesion: 0.20
Nodes (16): PrecompiledBelief, New(), seeded(), TestAHedgeCommitsToNothingSoNothingContradictsIt(), TestAPlantedContradictionIsCaught(), TestAWalkBackClearsTheWayForTheCorrectedClaim(), TestAWalkBackSupersedesRatherThanDeletes(), TestContradictionLookupIsScopedToTheSkill() (+8 more)

### Community 80 - "Community 80"
Cohesion: 0.24
Nodes (8): canonicalSkill(), canonicalStatement(), normalizeStance(), oppositeStance(), runtimeID(), stem(), Ledger, Claim

### Community 81 - "Community 81"
Cohesion: 0.32
Nodes (15): createInterview(), deleteCandidate(), enrollCandidates(), generateExpectation(), getAnalysisBody(), getExpectation(), getVoiceCapability(), listArchetypes() (+7 more)

### Community 82 - "Community 82"
Cohesion: 0.18
Nodes (8): ringFrame, SendRing, NewSendRing(), frameOf(), TestABumpInvalidatesEverythingQueued(), TestReadyIsAHintAndPopMayStillComeUpEmpty(), TestTheRingCopiesWhatItIsGiven(), TestTheRingDropsTheOldestNotTheNewest()

### Community 83 - "Community 83"
Cohesion: 0.12
Nodes (15): _configure(), db_path_from_env(), open_pool(), Connection, ConnectionPool, Storage wiring for the interview control-plane. Two backends live here during…, Database path from CONTROL_PLANE_DB, falling back to the default., Recordings directory from RECORDINGS_DIR, falling back to the default. (+7 more)

### Community 84 - "Community 84"
Cohesion: 0.18
Nodes (9): ContractSource, newSessionID(), actor, Manager, NewManager(), sync.RWMutex, DepsFactory, entry (+1 more)

### Community 85 - "Community 85"
Cohesion: 0.12
Nodes (17): MonkeyPatch, filesystem_store(), key(), monkeypatch_session(), fixture, Path, One bucket for this run. Keys are unique per test, so it can be shared., Both adapters, one test body. `getfixturevalue` rather than two fixtures in the… (+9 more)

### Community 86 - "Community 86"
Cohesion: 0.15
Nodes (15): _detail_message(), install_error_envelope(), main(), Entry point for the interview control-plane FastAPI service., Run the service with uvicorn., One human-readable line for a body of pydantic validation errors., The `message` string for an `HTTPException`'s detail, whatever its shape., Add `status` and `message` beside FastAPI's `detail` on every error. The… (+7 more)

### Community 87 - "Community 87"
Cohesion: 0.13
Nodes (16): Contract Source and Ingest Client, Idempotent Control-plane Session Ingest, Gap: Engine to Control-plane Authentication, Gap: Recording Drift Crash and Truncation Integrity, Persistence Plane, S3 Session Bundle, Presentation-timestamped Stereo Recorder, FFmpeg Audio-only Analysis Path (+8 more)

### Community 88 - "Community 88"
Cohesion: 0.12
Nodes (16): Planned Engine Gaps, Gradable Session Bundle, Hidden Interviewer Scorecard, Interviewer Training Rig, Persona-cohort Calibration, Judge Evidence Veto, Multilingual Scoring Validity Gap, Deterministic Report Engine (+8 more)

### Community 89 - "Community 89"
Cohesion: 0.17
Nodes (16): Candidate Identity Information, Candidate Persona, Full Reasoning Context, Harness Context Manager, Human Interviewer, Live Interviewer Input Transcription, Interview Details from Candidate Perspective, In-character Recall Phrase Covers Rare Direction Miss (+8 more)

### Community 90 - "Community 90"
Cohesion: 0.27
Nodes (7): Clock, newActor(), TestStoppingASessionCancelsEveryAlarmItArmed(), newTimerSet(), timerFire, timerKind, timerSet

### Community 91 - "Community 91"
Cohesion: 0.14
Nodes (12): _attempt_order(), call_with_failover(), Any, ChatMessage, T, Key indexes to try, the last known-good one first., Run ``invoke`` against each key in turn, stopping at the first success. Only a…, One JSON object, from whichever key answers. (+4 more)

### Community 92 - "Community 92"
Cohesion: 0.16
Nodes (16): classify(), extract(), _is_double_barrelled(), is_question(), Turn, Drop a discourse-marker opener so the first real word can be classified., Whether a sentence functions as a question or an elicitation. Deliberately does…, The question act's type, in strict precedence order (spec section 3.3). (+8 more)

### Community 93 - "Community 93"
Cohesion: 0.16
Nodes (12): QuestionAct, One question the manager asked. The unit of analysis — spec section 3.2., `mm:ss` on the session clock., assign(), _first_cue(), Pattern, Turn, Segmentation — spec section 3.1. Talk time and question mix mean different… (+4 more)

### Community 94 - "Community 94"
Cohesion: 0.18
Nodes (16): _count(), _fk_columns(), Connection, Deleting a persona must leave the transcript standing. The API answers 410 on…, Every cascade except the candidate one is intended to be real now. On SQLite…, The behaviour the missing FK exists for, asserted directly., The second reason the FK is absent: the upsert moves the key itself., `skills_required` is a list everywhere in the code; the CHECK says so. (+8 more)

### Community 95 - "Community 95"
Cohesion: 0.23
Nodes (14): appendRecordingChunk(), appendTranscript(), finalizeRecording(), mintRealtimeCredential(), recordingUrl(), connectGeminiLive(), fromBase64(), toBase64() (+6 more)

### Community 96 - "Community 96"
Cohesion: 0.15
Nodes (12): pick_voice(), Choose this persona's voice, deterministically and stably. Lives here rather…, _cast(), _DraftModel, A casting model that returns one fixed draft, with overrides., One catalog persona cast through the real agent against a fake model., The production bug: no `human_traits`, so nothing constrained the voice., `neutral` is an answer, and a missing key is not an error. (+4 more)

### Community 97 - "Community 97"
Cohesion: 0.19
Nodes (14): db(), _infra(), pg_admin_dsn(), pool(), Connection, ConnectionPool, fixture, Shared fixtures. Postgres today; the SQLite suites are untouched. Every fixture… (+6 more)

### Community 98 - "Community 98"
Cohesion: 0.20
Nodes (11): getSession(), recordingDownloadUrl(), CandidateCard(), fmtWhen(), initials(), InterviewDetail(), STATUS, band() (+3 more)

### Community 99 - "Community 99"
Cohesion: 0.34
Nodes (13): deferRig(), enterDefer(), actor, TestALowCeilingProbeReAssertsTheCeilingImmediately(), TestAMissedDeadlineFallsBackToTheContractsOwnDirective(), TestANeverUnlockPersonaCannotBeTalkedIntoUnlocking(), TestANoteArrivingInTimeIsInjectedAsContextNotSpokenVerbatim(), TestANoteForATurnThatHasMovedOnIsDiscarded() (+5 more)

### Community 100 - "Community 100"
Cohesion: 0.14
Nodes (12): Band, Criterion, load_rubric(), BaseModel, Path, Load the rubric, falling back to the built-in default. The caller resolves the…, One scored manager competency., A readiness band. `floor` is inclusive; the highest matching band wins. (+4 more)

### Community 101 - "Community 101"
Cohesion: 0.23
Nodes (13): build_turns(), loud_enough(), main(), Path, Turn a stereo session recording into a speaker-labelled turn list. The browser…, Merge time-ordered segments into speaker turns., Decode to 16 kHz mono WAVs, one per speaker channel., Per-window RMS, so a segment can be checked against its own channel. (+5 more)

### Community 102 - "Community 102"
Cohesion: 0.24
Nodes (12): AudioError, cut(), duration_ms(), Path, RuntimeError, Audio windowing for the analysis harness. Long recordings are cut into…, Cut the recording into windows, re-encoding each to a self-contained file. Re-…, The recording could not be read or cut. (+4 more)

### Community 103 - "Community 103"
Cohesion: 0.19
Nodes (11): build_session_system_prompt(), build_voice_system_prompt(), expectation_note(), Any, Persona and guardrails for the Virtual Candidate Agent. The agent writes only…, Ground the persona in the interview's expectation document when present., Compile the session system instruction: the contract, then text-mode rules.…, Compile the voice-session instructions: the contract, then spoken-mode rules.… (+3 more)

### Community 104 - "Community 104"
Cohesion: 0.21
Nodes (13): Layered Persona Ceiling Enforcement, Cognition Plane, Deterministic Pre-gate, Frozen Persona Engine Contract v1.1, Gap: Streaming ASR Choice and Capacity, Gap: Precompiled Belief and Lexicon Quality, Gap: Judge Precision and Walk-back Calibration, Gap: Stall Clip Voice Seam Is Unverified (+5 more)

### Community 105 - "Community 105"
Cohesion: 0.18
Nodes (13): Four-plane Architecture, Go Live-session Engine, SkillBrew Portal Integration, Provider Credential Operational Blocker, Current Spoken Practice Path, Text-first Bridge, Python Ports-and-adapters Architecture, ChatModel (+5 more)

### Community 106 - "Community 106"
Cohesion: 0.23
Nodes (6): ContractSource, SessionIngest, CeilingFlag, ObjectKeys, TurnIngest, UnlockFlip

### Community 108 - "Community 108"
Cohesion: 0.44
Nodes (11): micFrame(), newRig(), TestAnUnknownTicketIsRefused(), TestAPlayoutHeartbeatReachesTheSession(), TestATicketIsSingleUse(), TestMicAudioArrivesResampledAtTheRateTheSpeakerWants(), TestPersonaAudioReachesTheBrowser(), TestSendAudioNeverBlocksOnASlowBrowser() (+3 more)

### Community 109 - "Community 109"
Cohesion: 0.18
Nodes (8): _client(), GeminiChatModel, ChatMessage, Reject an empty completion — a silent blank turn stalls the session., Build the shared async Gemini client., Gemini backend for free-text conversation turns. The persona prompt goes in…, Call Gemini with the conversation so far and return the next turn., _require_text()

### Community 110 - "Community 110"
Cohesion: 0.20
Nodes (8): _FileByteSource, Clamp an inclusive `[start, end]` request to what the object holds. The…, A local file, read through the port's range rules., Stream the inclusive range, seeking rather than reading and slicing., One S3 object, sized once by `head_object` and then served by range., Stream the inclusive range with a ranged GET, or nothing at all. The empty case…, _resolve_range(), _S3ByteSource

### Community 111 - "Community 111"
Cohesion: 0.24
Nodes (8): EventLog, NewEventLog(), sortedFields(), newTestEventLog(), TestEventLogIsOrderedAndStampedFromTheSessionClock(), encoding/json.Encoder, io.Writer, Event

### Community 112 - "Community 112"
Cohesion: 0.26
Nodes (9): AnalysisPanel(), onAnalyse(), generateReport(), getAnalysisStatus(), getReport(), reportHtmlUrl(), startAnalysis(), ReportView() (+1 more)

### Community 113 - "Community 113"
Cohesion: 0.18
Nodes (11): build_gemini_live_session(), Compile the Gemini Live session document for one persona. Three keys, and the…, Stored at cast time, so the persona sounds the same everywhere., Same intent as `eagerness`, expressed as a silence timer., It is handed to the browser verbatim, so this is the whole no-leak rule., test_gemini_falls_back_to_the_same_rule_when_no_voice_was_stored(), test_gemini_instructions_carry_the_contract_prompt_and_the_opening_line(), test_gemini_speaks_in_the_voice_the_persona_was_cast_with() (+3 more)

### Community 114 - "Community 114"
Cohesion: 0.20
Nodes (11): get_analysis_body(), get_recording(), get_session_report(), get_session_report_html(), Any, Serve the session's recording, streamed off disk. Serves a partial recording…, The analysis itself — transcript, observations and assessments., The stored report for this session. (+3 more)

### Community 115 - "Community 115"
Cohesion: 0.20
Nodes (8): ByteSource, ObjectStore, Protocol, Bytes at rest, addressed by a logical key., Store the file at `source` under `key`, overwriting what was there., Open `key` for streaming, or `None` when no such object exists., An object opened for reading: how big it is, and how to stream it., Stream `[start, end]` — **inclusive** at both ends, like HTTP Range. `end=None`…

### Community 116 - "Community 116"
Cohesion: 0.24
Nodes (4): newTurnTable(), sentenceCounter, TurnRecord, turnTable

### Community 117 - "Community 117"
Cohesion: 0.20
Nodes (5): FakeBroker, FakeGeminiBroker, Any, Records the session document it was handed and returns a dummy secret. Answers…, A broker that answers ``gemini``: WebSocket, no call URL, its own roster.

### Community 118 - "Community 118"
Cohesion: 0.20
Nodes (6): ABC, ModelClient, Configuration every model port shares: which model, how warm, whose., The provider's model identifier, recorded alongside generated output., Sampling temperature this instance was configured with., Short provider name, e.g. ``gemini`` or ``openai``.

### Community 119 - "Community 119"
Cohesion: 0.36
Nodes (5): FilesystemObjectStore, Path, Objects as files under `root`. The default when no bucket is configured. The…, Copy `source` to `root/key`, creating parents, and record its type.…, Open `root/key`, or `None` when there is no such file.

### Community 121 - "Community 121"
Cohesion: 0.22
Nodes (7): build_role_facts_prompt(), Prompts for the evaluation layer. Every prompt here drafts *statements* for a…, Render the role-facts extraction prompt., Any, RoleFact, Draft one statement per fact key. Always returns every key, in order., Clamp the model's answer onto the fixed checklist.

### Community 122 - "Community 122"
Cohesion: 0.42
Nodes (9): from_db(), from_transcript(), main(), persona_block(), Any, Path, Build a report-engine bundle. The report engine is standalone and reads no…, Build from a plain turn list: [{speaker, text, elapsed_ms?}, ...]. (+1 more)

### Community 123 - "Community 123"
Cohesion: 0.22
Nodes (9): instructions(), The agent's operating instructions, as shipped. Read from the file rather than…, What the model is, and the rules it works under., system_prompt(), Speaker attribution is a fact from the stereo split, never a guess., test_the_instructions_forbid_scoring_and_candidate_assessment(), test_the_instructions_say_an_early_close_can_be_correct(), test_the_instructions_ship_with_the_package() (+1 more)

### Community 124 - "Community 124"
Cohesion: 0.22
Nodes (3): realClock, realTimer, time.Timer

### Community 125 - "Community 125"
Cohesion: 0.28
Nodes (7): _clamp(), penalty_count(), plateau(), Transfer functions — the only place a raw measurement becomes a score. Keeping…, Clamp to 0..10 and round. Rounding here rather than at each call site is what…, Full marks at zero, dropping `step` points per occurrence., Full marks inside [lo, hi], decaying linearly out to `ceiling`. Used where both…

### Community 126 - "Community 126"
Cohesion: 0.21
Nodes (8): _Anchored, _merge_coverage(), _merge_persona(), Protocol, One read of how the manager handled this candidate, across the windows.…, Coverage summed across windows, not averaged. An item covered in window one…, An observation carrying a timestamp — the only field the collector touches., _weakest()

### Community 127 - "Community 127"
Cohesion: 0.29
Nodes (8): Barge-in Cancellation and Draining, Gap: Echo-safe Barge-in Is Unproven, Inferred Gap: Natural Listener Backchannels Without Interruption, Gap: Long-session Vendor Resumption Is Unverified, Browser-confirmed Playout Tracker, Speaker Port, Urgent Correction by Cancel and Re-answer, Mid-sentence Direction Injection Is Forbidden

### Community 128 - "Community 128"
Cohesion: 0.32
Nodes (6): main(), Command line entrypoint. python -m report_engine bundle.json -o report.html…, Run the engine over one bundle file., `python -m report_engine` entrypoint., The full report as indented JSON., to_json()

### Community 129 - "Community 129"
Cohesion: 0.29
Nodes (7): dimension_catalog(), Every dimension and preset this module knows, serializable for a UI. The…, list_trait_dimensions(), Every dimension and preset `custom_personas` values must come from., The composer's radar chart plots these scores directly. Every preset in the…, test_dimension_catalog_has_every_taxonomy_dimension(), test_dimension_catalog_scores_are_present_and_ordered_with_their_presets()

### Community 132 - "Community 132"
Cohesion: 0.29
Nodes (7): Barge-in Draining and Heard-truth Truncation, Inferred Gap: Robust Turn Boundary Fusion and Repair, Gap: Unlock Specification Compilation Fidelity, Per-session Actor, Session Plane, Conversation State Machine, Engine-owned Monotonic Unlock State

### Community 133 - "Community 133"
Cohesion: 0.29
Nodes (5): BaseModel, Public models for the evaluation layer., One fact about the role the manager is expected to convey. The report counts…, Human label for the report and the picker., RoleFact

### Community 134 - "Community 134"
Cohesion: 0.33
Nodes (6): _collect(), Any, Validate, shift, reject out-of-range and de-duplicate. Returns drops., Whether two quotes are the same utterance heard twice., _same(), _AnchoredT

### Community 135 - "Community 135"
Cohesion: 0.33
Nodes (6): build_voice_session(), Compile the session document for whichever provider is wired up. Args:…, Compiling one vendor's document for another's endpoint fails unreadably., test_an_unknown_provider_is_refused_rather_than_guessed_at(), test_the_dispatcher_compiles_the_shape_the_provider_speaks(), test_the_dispatcher_passes_the_configured_transcriber_through()

### Community 136 - "Community 136"
Cohesion: 0.33
Nodes (6): Context Harness, Async Ceiling Judge, EngineContract v1.6, Knowledge Ceiling, Unlock Condition, Current Voice Fidelity Gap

### Community 137 - "Community 137"
Cohesion: 0.33
Nodes (6): Realtime Backpressure Policy, Voice-to-voice Latency Budget, Per-hop and Behaviour Observability, Vendor End-of-turn to First Audio, Realtime Call Cost Dominance, OpenAI Realtime WebRTC Path

### Community 138 - "Community 138"
Cohesion: 0.60
Nodes (6): Claims Ledger, Inferred Gap: Long-session Context Compaction Policy, Speaker, Thinker, One Brain Two Parts Visual Model, Speaker-only Voice Limitation

### Community 139 - "Community 139"
Cohesion: 0.33
Nodes (4): _norm(), Whitespace-collapsed, case-folded, NFKC — the form spans are matched in., Normalise every turn once; spans are matched against this form., Find a span verbatim in some turn, or reject the claim resting on it.

### Community 140 - "Community 140"
Cohesion: 0.53
Nodes (4): missing(), run(), check.sh script, skip()

### Community 141 - "Community 141"
Cohesion: 0.33
Nodes (6): skipif, _build_video_fixture(), Path, A live-mode VP8+Opus WebM: 150 s of video over 100 s of audio. `-live 1` is…, A camera track longer than the audio must not stretch the reported length. The…, test_duration_of_a_video_recording_is_the_length_of_its_audio()

### Community 142 - "Community 142"
Cohesion: 0.70
Nodes (4): endSession(), takeTurn(), fmt(), SessionView()

### Community 144 - "Community 144"
Cohesion: 0.50
Nodes (4): _merge_criteria(), One assessment per criterion, averaged across the windows that saw it., CriterionAssessment, The model's rating for one rubric criterion — an input, not the score.

### Community 145 - "Community 145"
Cohesion: 0.50
Nodes (4): Audio Analysis Contract, No Post-Session Manager Grader, Missing Engine Recording and Transcript Artifacts, Unwired Runtime Judge

### Community 146 - "Community 146"
Cohesion: 0.50
Nodes (4): CandidateSessionAgent, Text Mode Preamble, Typed Turn Model Round Trip, Two-to-Eight Second Typed Turn Latency

### Community 148 - "Community 148"
Cohesion: 0.67
Nodes (3): get_engine_contract(), EngineContract, What the Go interview-candidate engine pulls to run this persona.

### Community 149 - "Community 149"
Cohesion: 0.67
Nodes (3): Media Plane, Transport Port (WebRTC or WS/PCM), Chrome-free Browser Session Tab

### Community 150 - "Community 150"
Cohesion: 0.67
Nodes (3): Live Talking Engine, PNG Render of Live Talking Engine Harness, SVG Render of Live Talking Engine Harness

### Community 152 - "Community 152"
Cohesion: 0.67
Nodes (3): Key-Shaped Credential Failover, No Overload Retry or Backoff, Gemini Load Rate Limit

## Knowledge Gaps
- **82 isolated node(s):** `skillbrew/engine`, `rawListPackage`, `Store`, `createRequest`, `createResponse` (+77 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **21 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `S3ObjectStore` connect `Community 60` to `Community 40`, `Community 85`, `Community 5`, `Community 15`?**
  _High betweenness centrality (0.348) - this node is a cross-community bridge._
- **Why does `Conn` connect `Community 15` to `Community 34`, `Community 4`, `Community 36`, `Community 74`, `Community 82`, `Community 63`?**
  _High betweenness centrality (0.218) - this node is a cross-community bridge._
- **Why does `newConn()` connect `Community 15` to `Community 82`, `Community 4`, `Community 63`?**
  _High betweenness centrality (0.149) - this node is a cross-community bridge._
- **Are the 24 inferred relationships involving `ModelError` (e.g. with `AudioAnalysisAgent` and `CandidateSessionAgent`) actually correct?**
  _`ModelError` has 24 INFERRED edges - model-reasoned connections that need verification._
- **What connects `skillbrew/engine`, `rawListPackage`, `Store` to the rest of the system?**
  _82 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.04085801838610827 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.041536050156739814 - nodes in this community are weakly interconnected._