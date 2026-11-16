// Included at the end of the sketch, after all UI/game state declarations.
// Services advance independently of drawing. This is intentionally not a
// separate translation unit: the existing game state remains private here.

static void powerApplyCpu(uint16_t mhz) {
  if (getCpuFrequencyMhz() == mhz) return;
  if (!setCpuFrequencyMhz(mhz)) ++powerClockErrors;
}

void powerPrintStatus() {
  const esp_partition_t *part = esp_ota_get_running_partition();
  Serial.printf("POWER fw=%s cpu=%u stage=%u panel_sleep=%d usb=%d aod=%d light=%d "
                "sleep_count=%lu sleep_us=%llu sleep_errors=%lu last_error=%d "
                "clock_errors=%lu radio=%d audio=%d slot=%s offset=0x%lx\n",
    FW_VERSION, getCpuFrequencyMhz(), dimStage, powerPanelSleeping, usbPresent(),
    powerAlwaysOnClock, powerLightSleepEnabled, (unsigned long)powerSleepCount,
    (unsigned long long)powerSleepUs, (unsigned long)powerSleepErrors,
    (int)powerLastSleepError, (unsigned long)powerClockErrors, radioBusy(), audioBusy(),
    part ? part->label : "unknown", part ? (unsigned long)part->address : 0UL);
}

void updateBrightness(uint32_t now) {
  powerInitOnce();
  if (alarmRinging()) { screenOff = false; lastInteract = now; }
  if (pet.evolving() || pet.ceremony || pet.eating() || pet.showHeart()) lastInteract = now;
  TamaPower::Inputs in{now-lastInteract, powerBrightnessPct, screenOff,
    manualClockView, powerAlwaysOnClock, usbPresent(), pet.sleeping,
    alarmRinging(), otaBusy(), radioBusy(), audioBusy(),
    gTouchIrq || wasPressed || digitalRead(TP_INT)==LOW, powerLightSleepEnabled};
  powerPlan = TamaPower::decide(in);
  dimStage = powerPlan.dimStage;

  // The 1.6.7 QSPI driver waits for each transfer (POLL_END) before returning.
  // Never issue a display command from another task or while rendering.
  if (powerPlan.displayOff) {
    if (!powerPanelSleeping) {
      panel->setBrightness(0);
      panel->displayOff(); // DISPOFF + SLPIN; the shared MCU/touch rail stays on.
      powerPanelSleeping = true;
      powerRestoreBrightness = false;
      powerAppliedBrightness = 0;
    }
  } else {
    powerApplyCpu(240); // Restore before display/SD work, including after radio exit.
    if (powerPanelSleeping) {
      panel->displayOn();
      panel->setBrightness(0);
      powerPanelSleeping = false;
      powerRestoreBrightness = true;
      powerForceRender = true;
    }
    if (!powerRestoreBrightness && powerAppliedBrightness != powerPlan.brightness) {
      panel->setBrightness(powerPlan.brightness);
      powerAppliedBrightness = powerPlan.brightness;
    }
  }
  powerApplyCpu(powerPlan.cpuMHz);
}

void powerFinishFrame() {
  if (powerRestoreBrightness && !powerPanelSleeping) {
    panel->setBrightness(powerPlan.brightness);
    powerAppliedBrightness = powerPlan.brightness;
    powerRestoreBrightness = false;
  }
  powerForceRender = false;
}

void powerIdle() {
  if (digitalRead(TP_INT) == LOW) gTouchIrq = true;
  const bool eligible = powerPlan.maySleep && powerPanelSleeping && powerWakeReady &&
    !gTouchIrq && !wasPressed && !radioBusy() && !otaBusy() && !audioBusy() &&
    !alarmRinging() && !usbPresent() && Serial.available()==0;
  if (!eligible || (powerSleepRetryAt && !TamaPower::reached(millis(),powerSleepRetryAt))) {
    // Give the scheduler real idle time even on USB or while a radio session is active.
    delay(powerPanelSleeping ? 10 : 2);
    return;
  }
  // The UI battery cache is 2s; do not keep sleeping for that long after USB insertion.
  if (usbPresentNow()) { delay(10); return; }
  if (!audioPrepareSleep()) { delay(5); return; }
  // audioPrepareSleep reserves quiescent hardware. New cues remain queued.
  if (audioBusy() || gTouchIrq || wasPressed || digitalRead(TP_INT)==LOW ||
      radioBusy() || alarmRinging() || Serial.available()) {
    audioAfterWake();
    delay(1);
    return;
  }
  powerSleepRetryAt=0;
  // IDF's gpio_wakeup_enable also changes the ordinary interrupt type. Mask
  // that ISR during the level-triggered sleep window and always restore FALLING.
  gpio_intr_disable((gpio_num_t)TP_INT);
  esp_err_t err = gpio_wakeup_enable((gpio_num_t)TP_INT,GPIO_INTR_LOW_LEVEL);
  if (err==ESP_OK) err=esp_sleep_enable_timer_wakeup(TamaPower::SLEEP_POLL_US);
  const int64_t started = esp_timer_get_time();
  const bool cancelled=gTouchIrq || digitalRead(TP_INT)==LOW || audioBusy();
  if (err==ESP_OK && !cancelled) err=esp_light_sleep_start();
  const int64_t elapsed = esp_timer_get_time() - started;
  gpio_wakeup_disable((gpio_num_t)TP_INT);
  gpio_set_intr_type((gpio_num_t)TP_INT,GPIO_INTR_NEGEDGE);
  gpio_intr_enable((gpio_num_t)TP_INT);
  audioAfterWake(); // Every successful reservation is released, including failed sleeps.
  powerLastSleepError = err;
  if (err == ESP_OK && !cancelled) {
    ++powerSleepCount;
    if (elapsed > 0) powerSleepUs += (uint64_t)elapsed;
  } else if (err!=ESP_OK) {
    ++powerSleepErrors;
    powerSleepRetryAt = millis() + 1000UL;
    delay(10); // Never busy-spin if a driver/board rejects sleep.
  }
  if (esp_sleep_get_wakeup_cause()==ESP_SLEEP_WAKEUP_GPIO || digitalRead(TP_INT)==LOW)
    gTouchIrq = true;
}

void serviceCriticalTasks() {
  const uint32_t now = millis();
  pet.update(now); // Light-sleep retains live tick state; never re-run offline sync.
  static uint32_t lastAlarmPoll = 0;
  static bool wasAlarmRinging = false;
  if (now-lastAlarmPoll >= 1000UL) { lastAlarmPoll=now; alarmUpdate(rtcEpoch()); }
  const bool ringing = alarmRinging();
  if (ringing && !wasAlarmRinging) {
    radioOnAlarm(); // Preserves an OTA flash-write transaction until verified completion.
    gameOpen=sackOpen=gameMenuOpen=arcMenuOpen=arcTetrisOpen=arcSnakeOpen=arcMineOpen=false;
    moleOpen=rpsOpen=quizOpen=catchOpen=galleryOpen=kbOpen=clockOpen=cardOpen=false;
    feedMenuUntil=confirmUntil=0; choiceKind=0;
    galleryPmd.unload(); miniOpponentPmd.unload();
    screenOff=false; manualClockView=false; lastInteract=now; dimStage=0;
    alarmNotice=0; alarmNoticeUntil=0; powerForceRender=true;
    audioAlarmStart();
  } else if (!ringing && wasAlarmRinging) audioAlarmStop();
  wasAlarmRinging=ringing;
  static bool wasEvoReady=false, wasRunReady=false;
  const bool evo=pet.wantEvolveButton(), run=pet.canRunawayNow();
  if (evo && !wasEvoReady) sfxPlay(SFX_MEDAL);
  if (run && !wasRunReady) sfxPlay(SFX_DENY);
  wasEvoReady=evo; wasRunReady=run;

  if (alarmNotice && TamaPower::reached(now,alarmNoticeUntil)) {
    alarmNotice=0; alarmNoticeUntil=0; powerForceRender=true;
  }
  if (feedMenuUntil && TamaPower::reached(now,feedMenuUntil)) feedMenuUntil=0;
  if (confirmUntil && TamaPower::reached(now,confirmUntil)) confirmUntil=0;
  if (choiceKind && choiceUntil && TamaPower::reached(now,choiceUntil)) choiceKind=0;
  // Completing care must never depend on whether a frame is drawn.
  if (bathUntil && TamaPower::reached(now,bathUntil)) {
    bathUntil=0;
    if (bathPending) {
      bathPending=false; pet.clean();
      if (pmd.has(PMD_POSE)) {
        beh.mode=2; beh.act=PMD_POSE; beh.t0=now;
        beh.until=now+pmdActTotalMs(pmd.acts[PMD_POSE])*2;
      }
    }
  }
  audioService();
}

// Pause only minigame time while the display is off. The pet/RTC/alarm keep
// advancing. All deadlines are shifted together, so waking never costs lives
// or instantly skips a countdown/result screen.
void serviceGameLogic(uint32_t now) {
  static bool paused=false;
  static uint32_t pauseAt=0, lastBallStep=0;
  static uint16_t pausedMask=0;
  const uint16_t mask=(gameOpen?1:0)|(sackOpen?2:0)|(moleOpen?4:0)|(rpsOpen?8:0)|
    (quizOpen?16:0)|(catchOpen?32:0)|(arcTetrisOpen?64:0)|(arcSnakeOpen?128:0)|(arcMineOpen?256:0);
  if (powerPanelSleeping || alarmRinging() || otaBusy()) {
    if (!paused) { paused=true; pauseAt=now; pausedMask=mask; }
    return;
  }
  if (paused) {
    const uint32_t dt=now-pauseAt;
    if (mask==pausedMask) {
      uint32_t *deadlines[]={&gameOverUntil,&hitTime,&sackUntil,&sackOverUntil,&moleNextAt,
        &moleResultUntil,&moleStageBannerUntil,&rpsRevealUntil,&rpsResultUntil,
        &quizCountdownEnd,&quizFeedbackUntil,&catchEndAt,&catchResultUntil,&catchLastStep,
        &arcTNext,&arcTBanner,&arcSNext,&arcSBanner,&arcMClearUntil};
      for (auto d:deadlines) TamaPower::shiftDeadline(*d,dt);
    }
    lastBallStep=now; paused=false;
  }
  const bool physicsStep=now-lastBallStep>=85UL;
  if (physicsStep) lastBallStep=now;
  if (gameOpen) {
    if (gameOverUntil) { if (TamaPower::reached(now,gameOverUntil)) gameOpen=false; }
    else if (physicsStep) stepGame();
  }
  if (sackOpen) {
    if (sackOverUntil) { if (TamaPower::reached(now,sackOverUntil)) sackOpen=false; }
    else if (TamaPower::reached(now,sackUntil)) {
      sackNewHi=sackHits>pet.strHi; sackGain=pet.trainStrength(sackHits);
      sfxPlay(sackNewHi?SFX_MEDAL:SFX_PLAY); sackOverUntil=now+3500;
    } else if (physicsStep) sackShake*=0.84f;
  }
  if (moleOpen) {
    if (moleResultUntil) {
      if (TamaPower::reached(now,moleResultUntil)) {moleOpen=false;miniOpponentPmd.unload();}
    } else if (!moleStageBannerUntil || TamaPower::reached(now,moleStageBannerUntil)) {
      moleStageBannerUntil=0;
      if (TamaPower::reached(now,moleNextAt)) {molePickNew();sfxPlay(SFX_GAME_TICK);}
    }
  }
  if (rpsOpen) {
    if (rpsRevealUntil && TamaPower::reached(now,rpsRevealUntil)) {
      rpsRevealUntil=0; rpsPlayer=rpsCpu=-1;
      if (rpsRound>=5) {
        rpsNewHi=rpsWins>pet.rpsHi;if(rpsNewHi)pet.rpsHi=rpsWins;
        pet.minigameReward(rpsWins*4+rpsDraws);
        sfxPlay(rpsNewHi&&rpsWins?SFX_MEDAL:SFX_GAME_OVER);rpsResultUntil=now+4200;
      }
    }
    if(rpsResultUntil&&TamaPower::reached(now,rpsResultUntil)){rpsOpen=false;miniOpponentPmd.unload();}
  }
  if(quizOpen && quizFeedbackUntil && TamaPower::reached(now,quizFeedbackUntil)) {
    quizFeedbackUntil=0;
    if(quizCompleted){quizOpen=false;miniOpponentPmd.unload();}
    else {if(!quizWasCorrect)quizLevel=1;quiz151PrepareLevel();}
  }
  if(catchOpen) {
    if(catchResultUntil){if(TamaPower::reached(now,catchResultUntil))catchOpen=false;}
    else if(TamaPower::reached(now,catchEndAt)||catchLives==0)catchFinish(now);
    else if(now-catchLastStep>=38UL) {
      uint32_t steps=(now-catchLastStep)/38UL;if(steps>5)steps=5;
      catchLastStep+=steps*38UL;catchItemY+=(int16_t)(steps*catchSpeed());
      if(catchItemY>=350){
        if(abs(catchItemX-catchPetX)<=55){
          if(catchItemType==CATCH_ROCK){if(catchLives)--catchLives;sfxPlay(SFX_DENY);}
          else {catchScore+=catchValue(catchItemType);sfxPlay(SFX_PLAY);}
        }
        catchSpawnItem();
      }
    }
  }
  if(arcTetrisOpen&&!arcTOver&&TamaPower::reached(now,arcTNext)){arcTDrop();arcTNext=now+arcTDelay();}
  if(arcSnakeOpen&&!arcSOver&&TamaPower::reached(now,arcSNext)){arcSMove();arcSNext=now+arcSSpeed();}
  if(arcMineOpen&&arcMClearUntil&&TamaPower::reached(now,arcMClearUntil)){arcMSetupStage(arcMStage+1);sfxPlay(SFX_GAME_START);}
}

static void renderPowerSettings() {
  gfx->fillScreen(RGB565_BLACK);gfx->fillCircle(CX,CY,231,UI_BG_DAY);
  uiPrintCenter(koOr("절전 설정","POWER SETTINGS"),36,UI_INK,3);
  char text[64];
  snprintf(text,sizeof(text),"%s %s",koOr("상시 시계","CLOCK AOD"),powerAlwaysOnClock?"ON":"OFF");
  drawMenuRow(104,text,powerAlwaysOnClock);
  snprintf(text,sizeof(text),"%s %s",koOr("대기 절전","LIGHT SLEEP"),powerLightSleepEnabled?"ON":"OFF");
  drawMenuRow(168,text);
  uiPrintCenter(koOr("30초 감광 / 2분 화면 꺼짐","DIM 30s / OFF 2min"),246,UI_INK,1);
  uiPrintCenter(koOr("상시 시계는 배터리를 더 사용해요","AOD USES MORE BATTERY"),274,UI_TRACK,1);
  uiPrintCenter(koOr("USB 수동 시계는 계속 표시","USB: MANUAL CLOCK STAYS ON"),296,UI_TRACK,1);
  drawMenuRow(340,koOr("뒤로가기","BACK"));
}
