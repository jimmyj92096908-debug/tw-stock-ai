// UNDEPLOYED safe-routing gateway for the existing LINE Official Account.
// Unknown, follow, group and non-text events stay with the existing linewebhook
// rather than replacing undocumented legacy behavior.
import { createHmac } from 'node:crypto';
import { parseStockCode, verifyLineSignature } from './handler.mjs';

const STOCK_KINDS=new Set(['stock','rank','list','excluded']);
const MAX_BYTES=256000;

export function isStockCommandEvent(event) {
  // Routing and the stock candidate must have the same minimum contract.
  // Otherwise malformed stock-like events would be silently consumed instead
  // of reaching the original handler.
  if (event?.type!=='message' || event.mode==='standby' ||
      event.source?.type!=='user' ||
      typeof event.source.userId!=='string' || !event.source.userId ||
      event.message?.type!=='text' ||
      typeof event.message.text!=='string' ||
      typeof event.webhookEventId!=='string' || !event.webhookEventId ||
      typeof event.replyToken!=='string' || !event.replyToken) return false;
  return STOCK_KINDS.has(parseStockCode(event.message.text).kind);
}

function response(message,status) {
  return new Response(message,{status,headers:{'content-type':'text/plain; charset=utf-8'}});
}

function repackage(payload,events,secret) {
  const body=JSON.stringify({...payload,events});
  const signature=createHmac('sha256',secret).update(body,'utf8').digest('base64');
  return {body,signature};
}

// stockHandler is the single-account candidate with its own inbound log and
// reply tracker. forwardLegacy MUST point at a fixed trusted legacy webhook.
// This gateway is not the installed LINE webhook and has no configured channel.
export function createSingleAccountGateway({
  channelSecret, stockHandler, forwardLegacy, enabled=true
}) {
  return async function fetchHandler(request) {
    const path=new URL(request.url).pathname;
    if(request.method==='GET' && path==='/health') return response('ok',200);
    if(path!=='/' && path!=='/webhook') return response('Not found',404);
    if(request.method!=='POST') return response('Method not allowed',405);
    if(!enabled || !channelSecret ||
       typeof stockHandler!=='function' || typeof forwardLegacy!=='function')
      return response('Gateway unavailable',503);

    const contentLength=Number(request.headers.get('content-length'));
    if(Number.isFinite(contentLength) && contentLength>MAX_BYTES)
      return response('Payload too large',413);
    const rawBody=await request.text();
    if(Buffer.byteLength(rawBody,'utf8')>MAX_BYTES)
      return response('Payload too large',413);
    const originalSignature=request.headers.get('x-line-signature');
    if(!verifyLineSignature(rawBody,originalSignature,channelSecret))
      return response('Unauthorized',401);

    let payload;
    try {payload=JSON.parse(rawBody);}catch{return response('Invalid JSON',400);}
    if(!Array.isArray(payload?.events) || payload.events.length>20)
      return response('Invalid events',400);

    const stocks=payload.events.filter(isStockCommandEvent);
    const legacy=payload.events.filter(event=>!isStockCommandEvent(event));

    // Stock processing first: if it fails, do not send the legacy subset until
    // LINE redelivers. A successfully sent stock reply will be deduplicated by
    // its own persistent delivery state on the next attempt.
    if(stocks.length) {
      const part=legacy.length ? repackage(payload,stocks,channelSecret) :
        {body:rawBody,signature:originalSignature};
      const stockRequest=new Request(request.url,{
        method:'POST',headers:{
          'content-type':'application/json','x-line-signature':part.signature
        },body:part.body
      });
      let result;
      try { result=await stockHandler(stockRequest); }
      catch { return response('Stock handler unavailable',502); }
      if(!result || result.status<200 || result.status>=300)
        return response('Stock handler failed',502);
    }

    // Pass through exact bytes/signature for all-legacy delivery; for mixed
    // batches, re-sign only the filtered legacy subset with the SAME channel
    // secret. Never send stock events to the old echo handler or it might
    // consume their reply token and produce an incorrect/duplicate reply.
    if(legacy.length || payload.events.length===0) {
      const part=stocks.length ? repackage(payload,legacy,channelSecret) :
        {body:rawBody,signature:originalSignature};
      let result;
      try { result=await forwardLegacy(part.body,part.signature); }
      catch { return response('Legacy webhook unavailable',502); }
      const status=result instanceof Response ? result.status : result?.status;
      if(!Number.isInteger(status) || status<200 || status>=300)
        return response('Legacy webhook failed',502);
    }

    return response('OK',200);
  };
}
