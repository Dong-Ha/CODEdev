"""HTTP transport for AX Code-Dev; owns no mutable application state."""
import hmac
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse


def build_handler(context: dict):
    class Handler (BaseHTTPRequestHandler ):
        server_version ="AXCodeDevMVP/1.4"
        def _headers (self ,status :int ,mime :str ="application/json; charset=utf-8",length :int =0 ):
            self .send_response (status )
            self .send_header ("Content-Type",mime )
            self .send_header ("Content-Length",str (length ))
            self .send_header ("X-Content-Type-Options","nosniff")
            self .send_header ("Referrer-Policy","no-referrer")
            self .send_header ("Cache-Control","no-store")
            self .send_header ("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self .end_headers ()

        def _json (self ,status :int ,data :dict ):
            raw =json .dumps (data ,ensure_ascii =False ).encode ("utf-8")
            self ._headers (status ,length =len (raw ))
            self .wfile .write (raw )

        def _error (self ,exc :Exception ):
            status =exc .status if isinstance (exc ,context['ApiError'] )else 500 
            message =str (exc )if isinstance (exc ,context['ApiError'] )else "서버 내부 오류가 발생했습니다. 서버 터미널 로그를 확인하세요."
            self ._json (status ,{"ok":False ,"error":message })
            if not isinstance (exc ,context['ApiError'] ):
                self .log_error ("Internal error: %r",exc )

        def _origin_ok (self )->bool :
            hostname =self .headers .get ("Host","")
            if hostname not in {f"127.0.0.1:{context['PORT'] }",f"localhost:{context['PORT'] }"}:
                return False 
            origin =self .headers .get ("Origin")
            if origin and origin not in {f"http://127.0.0.1:{context['PORT'] }",f"http://localhost:{context['PORT'] }"}:
                return False 
            return True 

        def _agent_authorized (self )->bool :
            return bool (context['AGENT_TOKEN'] )and hmac .compare_digest (
            self .headers .get ("X-AX-Agent-Token",""),context['AGENT_TOKEN'] )

        def do_GET (self ):
            if not self ._origin_ok ():
                return self ._json (403 ,{"ok":False ,"error":"로컬 호스트 접속만 허용됩니다."})
            route =urlparse (self .path ).path 
            if route =="/api/bootstrap":
                store =context['read_store'] ()
                return self ._json (200 ,{"ok":True ,"token":context['CSRF'] ,"sample_path":str (context['SAMPLE'] .resolve ()),
                "last_workspace":store .get ("last_workspace",""),
                "config_file":str (context['CONFIG_FILE'] ),
                "version":"1.4.0","agent_intake_enabled":bool (context['AGENT_TOKEN'] ),
                "limitations":{"max_full_file_output_kb":64,"max_edit_source_mb":8,"large_file_patch":True }})
            if route =="/api/claude/status":
                return self ._json (200 ,{"ok":True ,**context['claude_status'] ()})
            if route =="/api/jobs":
                with context['LOCK'] :
                    return self ._json (200 ,{"ok":True ,"jobs":[context['public_job'] (context['JOBS'] [i ])for i in context['JOB_ORDER'] ]})
            if route .startswith ("/api/jobs/"):
                with context['LOCK'] :
                    job =context['JOBS'] .get (route .rsplit ("/",1 )[1 ])
                    if not job :
                        return self ._json (404 ,{"ok":False ,"error":"작업 기록을 찾을 수 없습니다."})
                    return self ._json (200 ,{"ok":True ,"job":context['public_job'] (job )})
            if route =="/api/history":
                with context['LOCK'] :
                    return self ._json (200 ,{"ok":True ,"history":[context['to_public'] (context['PROPOSALS'] [i ])for i in context['RECENT'] ]})
            if route =="/api/inbox":
                with context['LOCK'] :
                    return self ._json (200 ,{"ok":True ,"tasks":[context['public_handoff'] (context['HANDOFFS'] [i ])for i in context['HANDOFF_ORDER'] ]})
            if route =="/api/agent/handoffs"or route .startswith ("/api/agent/handoffs/"):
                if not self ._agent_authorized ():
                    return self ._json (403 ,{"ok":False ,"error":"에이전트 연동 인증이 필요합니다."})
                with context['LOCK'] :
                    if route =="/api/agent/handoffs":
                        return self ._json (200 ,{"ok":True ,"tasks":[context['public_handoff'] (context['HANDOFFS'] [i ])for i in context['HANDOFF_ORDER'] ]})
                    ident =route .rsplit ("/",1 )[1 ]
                    item =context['HANDOFFS'] .get (ident )
                    if not item :
                        return self ._json (404 ,{"ok":False ,"error":"작업 ID를 찾을 수 없습니다."})
                    return self ._json (200 ,{"ok":True ,"task":context['public_handoff'] (item )})
            if route .startswith ("/api/"):
                return self ._json (404 ,{"ok":False ,"error":"찾을 수 없는 API입니다."})
            asset ={"/":"index.html","/index.html":"index.html","/style.css":"style.css",
            "/app.js":"app.js","/run_console.css":"run_console.css"}.get (route )
            if not asset :
                return self ._headers (404 ,"text/plain",0 )
            path =context['WEB'] /asset 
            if not path .exists ():
                return self ._headers (404 ,"text/plain",0 )
            data =path .read_bytes ()
            mime ={"html":"text/html; charset=utf-8","css":"text/css; charset=utf-8",
            "js":"application/javascript; charset=utf-8"}[path .suffix [1 :]]
            self ._headers (200 ,mime ,len (data ))
            self .wfile .write (data )

        def do_POST (self ):
            if not self ._origin_ok ():
                return self ._json (403 ,{"ok":False ,"error":"허용되지 않은 Origin/Host입니다."})
            route =urlparse (self .path ).path 
            agent_api =route =="/api/agent/handoffs"
            if agent_api :
                if not self ._agent_authorized ():
                    return self ._json (403 ,{"ok":False ,"error":"에이전트 연동 인증이 필요합니다."})
            elif self .headers .get ("X-AX-Token")!=context['CSRF'] :
                return self ._json (403 ,{"ok":False ,"error":"요청 검증 토큰이 누락되었습니다."})
            if not self .headers .get ("Content-Type","").startswith ("application/json"):
                return self ._json (415 ,{"ok":False ,"error":"JSON 요청만 지원합니다."})
            try :
                length =int (self .headers .get ("Content-Length","0"))
                if not 0 <length <=context['MAX_REQUEST_BYTES'] :
                    raise context['ApiError'] ("요청 본문이 비어 있거나 크기 제한을 초과합니다.",413 )
                body =json .loads (self .rfile .read (length ))
                if not isinstance (body ,dict ):
                    raise context['ApiError'] ("JSON 객체를 전달하세요.")
                if agent_api :
                    return self ._json (202 ,{"ok":True ,"task":context['create_handoff'] (body )})
                if route =="/api/workspace":
                    root =context['resolve_workspace'] (body .get ("path"))
                    profile =context['profile_for'] (root )
                    scan =context['scan_workspace'] (root ,profile )
                    return self ._json (200 ,{"ok":True ,"path":str (root ),"name":root .name ,
                    "branch":context['git_branch'] (root ),"files":scan ["files"],
                    "scan":scan ["stats"],"total_files":scan ["stats"]["scanned_files"],
                    "configured":profile is not None ,
                    "config":profile if profile else context['default_profile'] (root ),
                    "is_sample":root ==context['SAMPLE'] .resolve ()})
                if route =="/api/config/save":
                    root =context['resolve_workspace'] (body .get ("workspace"))
                    profile =context['save_profile'] (root ,body .get ("config"),body .get ("expected_revision"))
                    scan =context['scan_workspace'] (root ,profile )
                    return self ._json (200 ,{"ok":True ,"config":profile ,
                    "editable_files":len (scan ["files"]),"scan":scan ["stats"],
                    "workspace":str (root )})
                if route =="/api/file":
                    root =context['resolve_workspace'] (body .get ("workspace"))
                    path =context['resolve_target'] (root ,body .get ("target"))
                    context['require_editable'] (root ,str (body .get ("target")))
                    return self ._json (200 ,{"ok":True ,"content":context['read_utf8'] (path )})
                if route =="/api/jobs":
                    return self ._json (202 ,{"ok":True ,"job":context['start_job'] ("human",body )})
                if route =="/api/jobs/handoff":
                    return self ._json (202 ,{"ok":True ,"job":context['start_job'] ("handoff",body )})
                if route =="/api/propose":
                    return self ._json (200 ,{"ok":True ,"proposal":context['propose'] (body )})
                if route =="/api/handoff/generate":
                    return self ._json (200 ,{"ok":True ,"proposal":context['generate_handoff'] (body .get ("id"))})
                if route in {"/api/apply","/api/reject","/api/undo"}:
                    action =route .rsplit ("/",1 )[1 ]
                    return self ._json (200 ,{"ok":True ,"proposal":context['change_status'] (body ,action )})
                if route =="/api/proposal":
                    with context['LOCK'] :
                        p =context['PROPOSALS'] .get (body .get ("id"))
                        if not p :
                            raise context['ApiError'] ("제안이 존재하지 않습니다.",404 )
                        return self ._json (200 ,{"ok":True ,"proposal":context['to_public'] (p ,True )})
                raise context['ApiError'] ("찾을 수 없는 API입니다.",404 )
            except (context['ApiError'] ,ValueError ,UnicodeError ,json .JSONDecodeError )as exc :
                self ._error (exc if isinstance (exc ,context['ApiError'] )else context['ApiError'] ("요청 데이터가 올바르지 않습니다."))
            except Exception as exc :
                self ._error (exc )

        def log_message (self ,fmt :str ,*args )->None :
            if self .path .startswith ("/api/"):
                print (f"[{context['timestamp'] ()}] {self .client_address [0 ]} {fmt %args }")

    return Handler
