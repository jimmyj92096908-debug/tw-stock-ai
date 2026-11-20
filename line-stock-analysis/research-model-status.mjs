// Research-only model status for the future LINE candidate.
// The source evidence is the already published immutable evaluation artifact.
// No DB credentials, LINE tokens, user messages or trade instructions.
import evaluation from '../models/tw-factor-ridge-1-evaluation.json' with { type: 'json' };
import artifact from '../models/tw-factor-ridge-1-research.json' with { type: 'json' };

export const RESEARCH_REPORT_URL =
  'https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/workflows/first-stage-report.yml';

export function formatResearchModelStatus(
  report=evaluation, model=artifact
) {
  // Do not present misleading success if the artifact is incomplete,
  // overwritten, or ever claims authorization to publish trading signals.
  if (!report || !model ||
      report.model_version !== model.version ||
      typeof report.holdout?.dates !== 'number' ||
      typeof report.holdout?.model_mean_net_excess !== 'number' ||
      !Number.isFinite(report.holdout.model_mean_net_excess) ||
      report.holdout_research_gate_passed !== false ||
      report.live_trading_approved !== false ||
      report.line_signal_delivery_approved !== false ||
      model.may_send_trade_signals !== false ||
      model.production_release_approved !== false ||
      report.holdout_is_pristine_independent_validation !== false) {
    return '研究模型驗證證據未通過，暫不提供研究模型資訊。';
  }
  const outOfSample = (report.holdout.model_mean_net_excess * 100).toFixed(2);
  const holdoutStart = model.holdout_from;
  const dataEnd = model.data_end;
  return [
    '台股 AI 研究模型｜僅供資訊查詢',
    '模型版本：' + model.version,
    '研究資料期間：' + model.data_start + '～' + dataEnd,
    '樣本外觀察：' + holdoutStart + ' 起，共 ' + report.holdout.dates + ' 個重疊觀察日',
    '扣假設交易成本後，相對同日基準平均五日差異：' + outOfSample + ' 個百分點',
    '績效驗收：未通過。此模型不可提供買賣訊號。',
    '該樣本外資料曾用於前一版模型檢視，並非全新獨立驗證。',
    '可查看最新已產生的研究報告：',
    RESEARCH_REPORT_URL,
    '新 LINE 股票查詢尚未正式切換；原有 LINE 服務維持不變。',
    '非即時行情、預測機率、投資建議或自動下單。'
  ].join('\n').slice(0, 4900);
}
