/* Share-count presentation v1. Never use this formatter for price, money or ratio. */
(()=>{'use strict';
function volume(value){if(value===null||value===undefined||value===''||!Number.isFinite(Number(value)))return '数据未提供';const n=Number(value);if(Math.abs(n)<10000)return String(n);const x=Math.round((Math.abs(n)/10000+Number.EPSILON)*100)/100;return (n<0?'-':'')+String(x)+'W';}
window.readingFormat=Object.freeze({volume,terms:window.TradingLabTerms});
})();
