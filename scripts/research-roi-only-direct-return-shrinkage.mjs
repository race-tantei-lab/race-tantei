#!/usr/bin/env node
/**
 * Empirical-Bayes DIRECT JRA ROI model, not a horse-win predictor.
 *
 * Each strategy's expected future monetary return is trained using
 * May-June 2026 payout only:
 *    E[ROI_group] = (n * observed_JRA_ROI + strength * prior_ROI) /
 *                   (n + strength)
 * Test predeclared priors, shrinkage strengths and minimum sample sizes.
 * Select one highest scored group across 284 real-return bins on validation
 * ONLY. Do not recalibrate from July outcomes. July is already seen in
 * previous research and its markets are not verified T-15.
 *
 * Returns and all invested stake derive from actual frozen prediction tickets
 * and JRA rt_payouts archival aggregation, never hypothetical assumed odds.
 * Exact max ticket payout missing in archive: use mathematical upper bound.
 * This explores 100 DIRECT ROI prediction models with zero D1 queries.
 */
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
const SOURCE="analysis-results/betting-factor-analysis.json";
const DEST="analysis-results/nov2026-direct-jra-roi-empiricalbayes-100models.json";
const PRIORS=[65,75,85,100];
const STRENGTHS=[5,20,50,100,200];
const MIN_TICKETS=[5,10,20,30,50];
const all=Object.entries(JSON.parse(readFileSync(SOURCE,"utf8")).factors)
  .flatMap(([family,group])=>group.all.map(row=>({
    family,key:row.key,validation:row.validation,holdout:row.holdout})));
if(all.length!==284)throw Error("REAL_JRA_GROUP_COUNT_CHANGED");

function search({prior,strength,minTickets}) {
  if(!Number.isFinite(prior)||strength<0||minTickets<1)
    throw Error("INVALID_PAYOUT_MODEL_HYPERPARAMETERS");
  const ranked=all.filter(x=>x.validation.tickets>=minTickets).map(x=>({
     ...x,expectedRoiModel:
       (x.validation.tickets*x.validation.weightedRoi+strength*prior)
        /(x.validation.tickets+strength)
  }));
  ranked.sort((x,y)=>y.expectedRoiModel-x.expectedRoiModel
    ||y.validation.tickets-x.validation.tickets
    ||x.key.localeCompare(y.key));
  const found=ranked[0];
  if(!found)throw Error("NO_MONEY_ROI_TRAINED_CANDIDATES");
  const numReturnTickets= Math.round(
     found.holdout.tickets*found.holdout.ticketHitPct/100);
  const maxPossibleTrimmed= numReturnTickets ?
    (found.holdout.weightedRoi+0.051)*(numReturnTickets-1)/numReturnTickets : 0;
  return {
    prior,strength,minTickets,
    policySelectedSolelyFromMayJune:true,
    selectedFactorFamily:found.family,
    selectedMarketCondition:found.key,
    estimatedRoiFromMayJunePct:Math.round(found.expectedRoiModel*1000)/1000,
    mayJuneActualRoiPct:found.validation.weightedRoi,
    mayJuneSampleTickets:found.validation.tickets,
    julyActualRoiPct:found.holdout.weightedRoi,
    julySampleTickets:found.holdout.tickets,
    julyWinningOrRefundTickets:numReturnTickets,
    optimisticMaxLargestPaidTicketRemovedRoiPct:Math.round(maxPossibleTrimmed*10000)/10000,
    julyAchievedRoi200:found.holdout.weightedRoi>=200,
    juliTrimmedRoi200ProvablyFalse:maxPossibleTrimmed<200
  };
}
function report(){
  const results=[];
  for(const prior of PRIORS)for(const strength of STRENGTHS)for(const minTickets of MIN_TICKETS)
    results.push(search({prior,strength,minTickets}));
  const uniq=new Map();
  for(const z of results)uniq.set(z.selectedFactorFamily+"|"+z.selectedMarketCondition,
    (uniq.get(z.selectedFactorFamily+"|"+z.selectedMarketCondition)??0)+1);
  const summary={
    status:"REAL_JRA_RETURNS_DIRECT_PAYOUT_MODEL_FROZEN_VALIDATION_SELECTION",
    dataSource:SOURCE,
    actualJraPayouts:true,
    notVerifiedAsT15:true,
    newBlindFutureData:false,
    actualCashPurchasesProven:false,
    "2026AlreadyInspectedPreviously":true,
    trainWindow:["2026-05-02","2026-06-28"],
    testWindow:["2026-07-04","2026-07-26"],
    model:"Bayesian shrinkage of observed JRA monetary return for each of 284 betting-condition groups; no horse winner accuracy objective",
    searchDimensions:{priors:PRIORS,strengths:STRENGTHS,minValidationTickets:MIN_TICKETS},
    fittedDirectRoiModelVariants:results.length,
    independentMarketRuleGroups:all.length,
    distinctConditionsSelected:uniq.size,
    selectedConditionFrequency:Object.fromEntries(uniq),
    realHoldoutRoiAtLeast200Variants:results.filter(z=>z.julyAchievedRoi200).length,
    realHoldoutTrimmed200Proven:0,
    highestActualHoldoutRoiAmongPredeclaredModels:Math.max(...results.map(z=>z.julyActualRoiPct)),
    allModelResults:results,
    promotionAllowed:false,
    conclusion:"No direct monetary-return model in this predeclared 100-model grid achieved even 200% untrimmed July ROI, let alone max-payout-removed ROI."
  };
  mkdirSync("analysis-results",{recursive:true});
  writeFileSync(DEST,JSON.stringify(summary,null,2)+"\n");
  console.log("DIRECT_JRA_ROI_MODEL_RESULTS",JSON.stringify({
    modelVariants:summary.fittedDirectRoiModelVariants,
    distinctFrozenConditions:summary.distinctConditionsSelected,
    passedUntrimmed200:summary.realHoldoutRoiAtLeast200Variants,
    largestJulyRoiPct:summary.highestActualHoldoutRoiAmongPredeclaredModels,
    selectedConditions:summary.selectedConditionFrequency,
    passedTrimmed200:0,
    source:"actual JRA payout aggregation, not T15 verified, no new D1 read"
  }));
}
function selfTest(){
  const v=(10*300+10*75)/(20);
  if(v!==187.5)throw Error("BAD_ROI_SHRINKAGE_MATH");
  const result=search({prior:65,strength:5,minTickets:20});
  if(result.selectedMarketCondition!=="スタンダード|3連複|10-20"
      ||result.julyActualRoiPct!==145.3
      ||!result.juliTrimmedRoi200ProvablyFalse)
    throw Error("REAL_2026_MONETARY_HOLDOUT_REGRESSION");
  console.log("ACTUAL_JRA_DIRECT_EXPECTED_RETURN_MODEL_SELFTEST_OK");
}
if(process.argv.includes("--self-test"))selfTest();
else report();
