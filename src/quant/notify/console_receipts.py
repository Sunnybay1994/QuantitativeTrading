"""Durable preview receipts and at-most-once automatic acknowledgement attempts."""
import datetime as dt
import hashlib
import json
import re
import sqlite3

from quant.execution.manual_reply_protocol import parse_reply


class Receipts:
    def __init__(self, root):
        root.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(root/'receipts.sqlite',timeout=10)
        self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, payload TEXT, ack TEXT, status TEXT, provider TEXT)')
        legacy=root/'received.json'
        if legacy.exists():
            for row in json.loads(legacy.read_text(encoding='utf-8')):
                self.db.execute('INSERT OR IGNORE INTO receipts VALUES (?,?,?,?,?)',
                                (row['message_id'],json.dumps(row,ensure_ascii=False),'','legacy',None))
            self.db.commit()

    def close(self):
        self.db.close()

    def receive(self,msg):
        text=re.sub(r'^(?:@_user_\d+\s*)+','',msg['text']).strip()
        row={k:msg[k] for k in ('message_id','text','sent_at')}
        row['text']=row['text'][:4000]
        row['received_at']=dt.datetime.now().isoformat()
        try:
            row['parsed']=parse_reply(text)
            parsed=row['parsed']
            detail=(f"{parsed['order_id']} v{parsed['version']} · {parsed['kind']}"
                    + (f" · 本次数量{parsed['quantity']}" if 'quantity' in parsed else '')
                    + (f" · 价格{parsed['price']}" if 'price' in parsed else '')
                    + (f" · 费用{parsed['fee'] if parsed['fee'] is not None else '待核'}" if 'fee' in parsed else ''))
            ack='【演练回报已收到】'+detail+'。仅完成格式解析，未核对真实成交、未计入账户。请勿重复下单。'
        except ValueError:
            row['parsed']=None
            ack='【消息已收到】当前为通信演练监听，未执行交易或记账。成交回报请使用测试消息中的固定格式。'
        with self.db:
            inserted=self.db.execute('INSERT OR IGNORE INTO receipts VALUES (?,?,?,?,?)',
                (msg['message_id'],json.dumps(row,ensure_ascii=False),ack,'queued',None)).rowcount
        return bool(inserted)

    def dispatch(self,send):
        for row in list(self.db.execute("SELECT * FROM receipts WHERE status='queued' ORDER BY rowid")):
            with self.db:
                claimed=self.db.execute("UPDATE receipts SET status='sending' WHERE id=? AND status='queued'",(row['id'],)).rowcount
            if not claimed:
                continue
            try:
                result=send(row['ack'],hashlib.sha256(('console:'+row['id']).encode()).hexdigest()[:32])
                if result.get('provider_accepted') is not True or not result.get('message_id'):
                    raise ValueError('not accepted')
                state,provider='accepted',result['message_id']
            except Exception:
                state,provider='uncertain',None
            with self.db:
                self.db.execute('UPDATE receipts SET status=?,provider=? WHERE id=?',(state,provider,row['id']))

    def recent(self):
        return [{**json.loads(row['payload']),'ack_status':row['status']} for row in reversed(list(self.db.execute('SELECT * FROM receipts ORDER BY rowid DESC LIMIT 30')))]
