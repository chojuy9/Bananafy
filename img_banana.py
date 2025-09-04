import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, scrolledtext
import google.generativeai as genai
from PIL import Image, ImageTk
import json
import io
import os
from functools import partial
import threading
import queue

# API 키를 저장할 파일 이름
API_KEY_FILE = "api_key.txt"

class ImagePipelineApp:


    def clear_pipeline(self):
        """현재 파이프라인의 모든 노드를 GUI에서 제거하고 리스트를 비웁니다."""
        for node in self.pipeline_nodes:
            node["frame"].destroy()
        self.pipeline_nodes.clear()
        self.update_status("파이프라인이 초기화되었습니다.")

    def save_workflow(self):
        """현재 파이프라인의 상태를 JSON 파일로 저장합니다."""
        if not self.pipeline_nodes:
            messagebox.showwarning("저장할 내용 없음", "저장할 파이프라인 노드가 없습니다.")
            return

        filepath = filedialog.asksaveasfilename(
            initialdir=self.WORKFLOW_DIR, defaultextension=".json", filetypes=[("JSON Workflow", "*.json"), ("All Files", "*.*")],
            title="워크플로우 저장"
        )
        if not filepath: return

        workflow_data = []
        for node in self.pipeline_nodes:
            # --- BUG FIX: 부모 노드(연결 정보)를 함께 저장합니다. ---
            parent_selection = node["parent_var"].get()
            # --- [EXE 빌드 수정] 이미지 경로를 상대 경로로 변환하여 저장 ---
            relative_image_path = None
            if node["node_image_path"]:
                try:
                    # BASE_DIR를 기준으로 상대 경로 계산
                    relative_image_path = os.path.relpath(node["node_image_path"], self.BASE_DIR)
                except ValueError:
                    # 다른 드라이브에 있는 경우 등 상대 경로 계산이 불가능하면 절대 경로 유지
                    relative_image_path = node["node_image_path"]

            node_data = {
                "name": node["name_entry"].get(),
                "prompt": node["prompt_entry"].get(),
                "image_path": relative_image_path, # 변환된 상대 경로 저장
                "parent": parent_selection
            }
            # -------------------------------------------------------------
            # ----------------------------------------------------
            workflow_data.append(node_data)
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(workflow_data, f, indent=2, ensure_ascii=False)

            self.is_workflow_saved = True # [로드맵 5] 저장 성공 시 플래그 True
            # [로드맵 6] 현재 워크플로우 이름 업데이트
            self.current_workflow_name = os.path.splitext(os.path.basename(filepath))[0]
            
            self.update_status(f"워크플로우가 '{os.path.basename(filepath)}'에 저장되었습니다.")
        except Exception as e:
            messagebox.showerror("저장 실패", f"워크플로우 저장 중 오류 발생: {e}")

    def load_workflow(self):
        """JSON 파일에서 워크플로우를 불러옵니다."""
        filepath = filedialog.askopenfilename(
            initialdir=self.WORKFLOW_DIR, filetypes=[("JSON Workflow", "*.json"), ("All Files", "*.*")],
            title="워크플로우 불러오기"
        )
        if not filepath: return
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                workflow_data = json.load(f)
            
            self.clear_pipeline()
            
            for node_data in workflow_data:
                # --- [EXE 빌드 수정] 상대 경로를 다시 절대 경로로 변환하여 사용 ---
                image_path = node_data.get("image_path", None)
                if image_path and not os.path.isabs(image_path):
                    # 경로가 상대 경로이면, BASE_DIR와 조합하여 절대 경로로 만듦
                    image_path = os.path.join(self.BASE_DIR, image_path)
                
                parent_name = node_data.get("parent", "이전 노드")
                self.add_pipeline_node(
                    name=node_data.get("name", ""),
                    prompt=node_data.get("prompt", ""),
                    image_path=image_path, # 변환된 절대 경로 사용
                    parent_name=parent_name
                )
                # -------------------------------------------------------------
            self.is_workflow_saved = True # [로드맵 5] 로드 성공 시 플래그 True
            # [로드맵 6] 현재 워크플로우 이름 업데이트
            self.current_workflow_name = os.path.splitext(os.path.basename(filepath))[0]
            
            self.update_status(f"'{os.path.basename(filepath)}'에서 워크플로우를 불러왔습니다.")
        except Exception as e:
            messagebox.showerror("불러오기 실패", f"워크플로우 로드 중 오류 발생: {e}")

    def __init__(self, root):
        self.root = root
        self.root.title("Bananafy V1.3.01")
        self.root.geometry("1200x800")
        
        # --- [EXE 빌드 수정] 프로그램의 절대 경로를 기준점으로 설정 ---
        if getattr(sys, 'frozen', False):
            # .exe로 실행될 경우
            self.BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
        else:
            # .py 스크립트로 실행될 경우
            self.BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        
        self.PROMPT_DIR = os.path.join(self.BASE_DIR, "prompts")
        self.WORKFLOW_DIR = os.path.join(self.BASE_DIR, "workflows")
        self.OUTPUT_DIR = os.path.join(self.BASE_DIR, "img")
        # -----------------------------------------------------------

        # 변수 초기화
        self.base_image_path = None
        self.system_prompt_path = None
        self.system_prompt_data = {}
        self.pipeline_nodes = []
        self.node_outputs = {}
        self.api_key = self.load_api_key()

        # --- [스레딩] GUI 업데이트를 위한 큐 생성 ---
        self.ui_queue = queue.Queue()
        # ----------------------------------------

        # --- [로드맵 5] 워크플로우 저장 상태 플래그 ---
        self.is_workflow_saved = True
        # -------------------------------------------
        
        # --- [로드맵 6] 현재 워크플로우 이름 ---
        self.current_workflow_name = "untitled"
        # -------------------------------------
        
        # --- [로드맵 2] 프로그램 시작 시 폴더 자동 생성 ---
        os.makedirs(self.PROMPT_DIR, exist_ok=True)
        os.makedirs(self.WORKFLOW_DIR, exist_ok=True)
        os.makedirs(self.OUTPUT_DIR, exist_ok=True)
        # ---------------------------------------------

        self.setup_ui()

        if not self.api_key:
            self.request_api_key()

        # --- [스레딩] 100ms마다 큐를 확인하는 루프 시작 ---
        self.root.after(100, self.process_ui_queue)
        # ---------------------------------------------

    def process_ui_queue(self):
        """UI 큐를 주기적으로 확인하여 GUI 업데이트 작업을 처리합니다."""
        try:
            # 큐에서 메시지를 논블로킹으로 가져옴
            message = self.ui_queue.get_nowait()
            
            # 메시지 포맷: (명령, 데이터)
            command, data = message
            
            if command == "update_status":
                self.update_status(data)
            elif command == "display_image":
                # 데이터: (결과 이미지, 대상 노드 정보)
                image, target_node = data
                self.display_image(image, target_node["result_image_label"])
            elif command == "show_info":
                messagebox.showinfo("완료", data)
            elif command == "show_error":
                messagebox.showerror("오류", data)

        except queue.Empty:
            # 큐가 비어있으면 아무것도 하지 않음
            pass
        finally:
            # 100ms 후에 다시 이 함수를 호출
            self.root.after(100, self.process_ui_queue)

    def start_pipeline_thread(self):
        """파이프라인 실행을 위한 작업자 스레드를 생성하고 시작합니다."""
        # --- 스레드를 시작하기 전에 메인 스레드에서 유효성 검사를 먼저 수행합니다 ---
        if not self.is_workflow_saved:
            response = messagebox.askyesnocancel("경고", "저장되지 않은 변경사항이 있습니다.\n저장하지 않고 계속 실행하시겠습니까?", icon='warning')
            if response is None: return
            if not response:
                self.save_workflow()
                if not self.is_workflow_saved: return
        
        if not all([self.base_image_path, self.system_prompt_data, self.pipeline_nodes, self.api_key]):
            messagebox.showwarning("준비 부족", "기본 이미지, 시스템 프롬프트, API키, 그리고 하나 이상의 노드가 필요합니다.")
            return
        # -----------------------------------------------------------------

        self.execute_btn.config(state="disabled", text="실행 중...")
        
        thread = threading.Thread(target=self.execute_pipeline, daemon=True)
        thread.start()

    def _mark_dirty(self, event=None):
        """워크플로우가 수정되었음을 표시하는 'dirty flag'를 설정합니다."""
        if self.is_workflow_saved: # 상태가 변경될 때만 메시지 업데이트
            self.update_status("워크플로우에 저장되지 않은 변경사항이 있습니다.")
        self.is_workflow_saved = False

    def load_api_key(self):
        if os.path.exists(API_KEY_FILE):
            with open(API_KEY_FILE, 'r') as f: return f.read().strip()
        return None

    def save_api_key(self, key):
        with open(API_KEY_FILE, 'w') as f: f.write(key)

    def request_api_key(self):
        key = simpledialog.askstring("API 키 필요", "Google AI Studio에서 발급받은 API 키를 입력하세요:", show='*')
        if key:
            self.api_key = key
            self.save_api_key(key)
            self.update_status("API 키가 저장되었습니다.")
        else:
            messagebox.showerror("오류", "API 키가 없어 프로그램을 종료합니다.")
            self.root.quit()

    def setup_ui(self):
        top_frame = tk.Frame(self.root, pady=10)
        top_frame.pack(fill=tk.X)

        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        global_frame = tk.LabelFrame(main_frame, text="전역 설정", padx=10, pady=10, width=350)
        global_frame.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=5)
        global_frame.pack_propagate(False)

        # --- 신규: 워크플로우 저장/불러오기 버튼 추가 ---
        workflow_frame = tk.Frame(global_frame)
        workflow_frame.pack(fill=tk.X, pady=(0, 10))
        btn_save = tk.Button(workflow_frame, text="워크플로우 저장", command=self.save_workflow)
        btn_save.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
        btn_load = tk.Button(workflow_frame, text="워크플로우 불러오기", command=self.load_workflow)
        btn_load.pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=(5, 0))
        # ------------------------------------------------

        btn_img = tk.Button(global_frame, text="1. 기본 이미지 선택 (캐릭터 등)", command=self.select_base_image)
        btn_img.pack(fill=tk.X, pady=5)
        self.base_image_preview = tk.Label(global_frame, text="기본 이미지 미리보기", relief=tk.RIDGE)
        self.base_image_preview.pack(fill=tk.X, pady=5)

        btn_prompt = tk.Button(global_frame, text="2. 시스템 프롬프트 (JSON)", command=self.select_system_prompt)
        btn_prompt.pack(fill=tk.X, pady=5)
        self.system_prompt_preview = scrolledtext.ScrolledText(global_frame, height=10, state='disabled')
        self.system_prompt_preview.pack(fill=tk.BOTH, expand=True, pady=5)

        pipeline_container = tk.LabelFrame(main_frame, text="파이프라인 편집기", padx=10, pady=10)
        pipeline_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=5)

        btn_add_node = tk.Button(pipeline_container, text="+ 파이프라인 노드 추가", command=self.add_pipeline_node, bg="green", fg="white")
        btn_add_node.pack(fill=tk.X, pady=5)
        
        canvas = tk.Canvas(pipeline_container)
        scrollbar = tk.Scrollbar(pipeline_container, orient="vertical", command=canvas.yview)
        self.pipeline_frame = tk.Frame(canvas)

        self.pipeline_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.pipeline_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        bottom_frame = tk.Frame(self.root)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)
        # --- [로드맵 3] 실행 버튼과 반복 횟수 위젯을 한 프레임에 묶기 ---
        run_frame = tk.Frame(bottom_frame)
        run_frame.pack(fill=tk.X, padx=10, pady=10)

        # --- [스레딩] 버튼의 command를 스레드 시작 함수로 변경 ---
        self.execute_btn = tk.Button(run_frame, text="전체 파이프라인 실행", command=self.start_pipeline_thread, height=2, bg="blue", fg="white", font=("Helvetica", 12, "bold"))
        self.execute_btn.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        # ----------------------------------------------------

        batch_label = tk.Label(run_frame, text="반복:")
        batch_label.pack(side=tk.LEFT, padx=(10, 2))
        self.batch_spinbox = tk.Spinbox(run_frame, from_=1, to=100, width=5, font=("Helvetica", 12))
        self.batch_spinbox.pack(side=tk.LEFT, fill=tk.Y, expand=True)
        # -----------------------------------------------------------
        self.status_label = tk.Label(bottom_frame, text="준비 완료", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

    def add_pipeline_node(self, name="", prompt="", image_path=None, parent_name="previous"):
        """
        파이프라인에 새 노드를 추가합니다.
        '부모 노드'를 지정할 수 있는 드롭다운 메뉴를 포함합니다.
        """
        node_index = len(self.pipeline_nodes)
        node_frame = tk.LabelFrame(self.pipeline_frame, text=f"Node Index #{node_index + 1}", padx=10, pady=10)
        node_frame.pack(fill=tk.X, pady=5, padx=5)

        top_pane = tk.Frame(node_frame)
        top_pane.pack(fill=tk.X, pady=(0, 5))
        
        parent_label = tk.Label(top_pane, text="입력:")
        parent_label.pack(side=tk.LEFT, padx=(0, 5))
        parent_var = tk.StringVar(self.root)
        # OptionMenu는 나중에 update_all_parent_dropdowns에서 채워지므로 초기값만 설정
        parent_dropdown = tk.OptionMenu(top_pane, parent_var, "이전 노드")
        parent_dropdown.pack(side=tk.LEFT, padx=(0, 10))
        
        name_label = tk.Label(top_pane, text="노드 이름:")
        name_label.pack(side=tk.LEFT, padx=(10, 5))
        name_entry = tk.Entry(top_pane)
        name_entry.pack(fill=tk.X, expand=True)
        default_name = name if name else f"노드_{node_index + 1}"
        name_entry.insert(0, default_name)
        name_entry.bind("<KeyRelease>", self.update_all_parent_dropdowns)

        # --- [로드맵 4] 개별 노드 실행 버튼 추가 ---
        # node_info를 미리 정의해야 lambda에서 참조 가능
        node_info = {} 
        run_node_btn = tk.Button(top_pane, text="▶ 실행", command=lambda: self.execute_single_node(node_info), fg="blue", font=("Helvetica", 8))
        run_node_btn.pack(side=tk.RIGHT, padx=(5,0))
        # -----------------------------------------
        
        content_frame = tk.Frame(node_frame)
        content_frame.pack(fill=tk.BOTH, expand=True)
        left_pane = tk.Frame(content_frame)
        left_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        right_pane = tk.Frame(content_frame)
        right_pane.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # --- BUG FIX: node_info 딕셔너리를 모든 위젯이 생성된 후에 만듭니다. ---
        node_info = {
            "frame": node_frame, "name_entry": name_entry, "parent_var": parent_var,
            "parent_dropdown": parent_dropdown, "node_image_path": image_path
        }

        node_image_btn = tk.Button(left_pane, text="노드 참조 이미지 불러오기 (포즈 등)", command=lambda: self.select_node_image(node_info))
        node_image_btn.pack(fill=tk.X)
        node_image_preview = tk.Label(left_pane, text="참조 이미지 없음", bg="gray95", relief=tk.SUNKEN)
        node_image_preview.pack(fill=tk.X, pady=5)
        if image_path and os.path.exists(image_path):
            self.display_image(image_path, node_image_preview)

        prompt_label = tk.Label(left_pane, text="보조 프롬프트:")
        prompt_label.pack(anchor=tk.W, pady=(10, 0))
        prompt_entry = tk.Entry(left_pane)
        prompt_entry.pack(fill=tk.X, pady=2)
        prompt_entry.insert(0, prompt)
        prompt_entry.bind("<KeyRelease>", self._mark_dirty)
        
        result_image_label = tk.Label(right_pane, text="결과 미리보기", bg="gray90")
        result_image_label.pack(fill=tk.BOTH, expand=True)

        remove_btn = tk.Button(node_frame, text="X", fg="red", command=lambda: self.remove_node(node_frame))
        remove_btn.place(relx=1.0, rely=0, anchor='ne')

        # node_info 딕셔너리에 나머지 위젯 정보를 추가합니다.
        node_info.update({
            "frame": node_frame, "name_entry": name_entry, "parent_var": parent_var,
            "parent_dropdown": parent_dropdown, "node_image_path": image_path,
            "prompt_entry": prompt_entry, "result_image_label": result_image_label,
            "node_image_preview": node_image_preview
        })
        # -------------------------------------------------------------------

        self.pipeline_nodes.append(node_info)
        
        # parent_var의 값을 설정하고 모든 드롭다운을 업데이트합니다.
        if parent_name == "previous": parent_var.set("이전 노드")
        elif parent_name == "global": parent_var.set("전역 기본 이미지")
        else: parent_var.set(parent_name)
        self.update_all_parent_dropdowns()
        
        if not name:
            self.update_status(f"노드 #{node_index + 1} 추가됨.")
            self._mark_dirty()

    def update_all_parent_dropdowns(self, event=None):
        """모든 노드의 부모 선택 드롭다운 메뉴를 최신 노드 이름 목록으로 업데이트합니다."""
        current_node_names = [node["name_entry"].get() for node in self.pipeline_nodes]
        new_options = ["이전 노드", "전역 기본 이미지"] + current_node_names
        
        for node in self.pipeline_nodes:
            dropdown = node["parent_dropdown"]
            parent_var = node["parent_var"]
            current_selection = parent_var.get()

            menu = dropdown["menu"]
            menu.delete(0, "end")

            for option in new_options:
                # --- BUG FIX: partial을 사용하여 각 command가 올바른 변수를 참조하도록 수정 ---
                # "parent_var.set" 이라는 함수에 "option" 이라는 값을 미리 '박제'해서 새로운 함수를 만듭니다.
                command = partial(parent_var.set, option)
                menu.add_command(label=option, command=command)
                # -------------------------------------------------------------------------

            if current_selection in new_options:
                parent_var.set(current_selection)
            else:
                parent_var.set("이전 노드")
        
        if event: # 실제 키 입력으로 호출된 경우에만 dirty 처리
            self._mark_dirty()

    def select_node_image(self, node_info):
        """특정 노드의 참조 이미지를 선택하는 함수"""
        path = filedialog.askopenfilename(filetypes=(("이미지 파일", "*.png *.jpg *.jpeg *.webp"), ("모든 파일", "*.*")))
        if path:
            node_info["node_image_path"] = path
            self.display_image(path, node_info["node_image_preview"])
            self.update_status(f"노드 #{self.pipeline_nodes.index(node_info) + 1}에 참조 이미지 로드됨.")
            self._mark_dirty()

    def remove_node(self, node_frame_to_remove):
        for i, node in enumerate(self.pipeline_nodes):
            if node["frame"] == node_frame_to_remove:
                self.pipeline_nodes.pop(i)
                break
        node_frame_to_remove.destroy()
        self.reindex_nodes()
        self.update_status("노드 제거됨.")
        self._mark_dirty()

    def reindex_nodes(self):
        for i, node in enumerate(self.pipeline_nodes):
            node["frame"].config(text=f"노드 #{i + 1}")

    def select_base_image(self):
        path = filedialog.askopenfilename(filetypes=(("이미지 파일", "*.png *.jpg *.jpeg *.webp"), ("모든 파일", "*.*")))
        if path:
            self.base_image_path = path
            self.display_image(self.base_image_path, self.base_image_preview)
            self.update_status("기본 이미지 선택됨.")

    def select_system_prompt(self):
        path = filedialog.askopenfilename(initialdir=self.PROMPT_DIR, filetypes=(("JSON 파일", "*.json"), ("모든 파일", "*.*")))
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self.system_prompt_data = json.load(f)
                    pretty_json = json.dumps(self.system_prompt_data, indent=2, ensure_ascii=False)
                    self.system_prompt_preview.config(state='normal')
                    self.system_prompt_preview.delete('1.0', tk.END)
                    self.system_prompt_preview.insert(tk.END, pretty_json)
                    self.system_prompt_preview.config(state='disabled')
                    self.update_status("시스템 프롬프트 로드 완료.")
            except Exception as e:
                messagebox.showerror("오류", f"JSON 파일 로드 실패: {e}")

    def display_image(self, image_source, label_widget):
        FIXED_DISPLAY_HEIGHT = 150
        try:
            if isinstance(image_source, str): img = Image.open(image_source)
            else: img = image_source.copy()
            img_w, img_h = img.size
            if img_h == 0: return
            ratio = img_w / img_h
            new_h = FIXED_DISPLAY_HEIGHT
            new_w = int(new_h * ratio)
            resized_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(resized_img)
            label_widget.config(image=photo, text="")
            label_widget.image = photo
        except Exception as e:
            self.update_status(f"이미지 표시 오류: {e}")
            
    def update_status(self, message):
        self.status_label.config(text=message)
        self.root.update_idletasks()

    def execute_pipeline(self):
        """(작업자 스레드에서 실행됨) 파이프라인의 핵심 로직을 수행합니다."""
        try:
            # 1. 반복 횟수 가져오기 (이 작업은 스레드에 안전합니다)
            try:
                iterations = int(self.batch_spinbox.get())
            except ValueError:
                iterations = 1

            # 2. API 설정 (기존과 동일)
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel('gemini-2.5-flash-image-preview')
            system_prompt = self.system_prompt_data.get("prompt", "")

            # 3. 전체 파이프라인을 반복 횟수만큼 실행
            for batch_index in range(iterations):
                # GUI 업데이트: 큐를 통해 상태 메시지 전송
                self.ui_queue.put(("update_status", f"--- 배치 {batch_index + 1}/{iterations} 시작 ---"))

                # 결과물 캐시 초기화 (기존과 동일)
                self.node_outputs = {
                    "전역 기본 이미지": Image.open(self.base_image_path)
                }
                
                # 현재 배치의 파이프라인 노드를 순서대로 실행
                for i, node in enumerate(self.pipeline_nodes):
                    node_name = node["name_entry"].get().strip()
                    if not node_name: node_name = f"이름없는_노드_{i+1}"
                    
                    # GUI 업데이트: 큐를 통해 상태 메시지 전송
                    self.ui_queue.put(("update_status", f"배치 {batch_index + 1}/{iterations} - 노드 '{node_name}' 실행 중..."))

                    # 3-1. 입력 이미지 결정 (기존 로직과 완전히 동일)
                    parent_selection = node["parent_var"].get()
                    input_image = None
                    if parent_selection == "이전 노드":
                        if i == 0:
                            input_image = self.node_outputs["전역 기본 이미지"]
                        else:
                            previous_node_name = self.pipeline_nodes[i - 1]["name_entry"].get().strip()
                            if not previous_node_name: previous_node_name = f"이름없는_노드_{i}"
                            if previous_node_name not in self.node_outputs: raise ValueError(f"'{previous_node_name}' 노드의 결과물을 찾을 수 없습니다.")
                            input_image = self.node_outputs[previous_node_name]
                    else:
                        if parent_selection not in self.node_outputs: raise ValueError(f"입력으로 지정된 '{parent_selection}'는 아직 실행되지 않았거나 존재하지 않는 노드입니다.")
                        input_image = self.node_outputs[parent_selection]

                    # 3-2. API 호출 (기존 로직과 완전히 동일)
                    aux_prompt = node["prompt_entry"].get()
                    instructional_prefix = "You are an image generation pipeline. Follow the user's instructions precisely. Generate a single image as the output. Do not respond with text."
                    full_prompt = f"{instructional_prefix}\n\n## System Prompt:\n{system_prompt}\n\n## User Instruction for this step:\n{aux_prompt}"
                    contents = [full_prompt, input_image]
                    if node["node_image_path"]:
                        contents.append(Image.open(node["node_image_path"]))
                    
                    response = model.generate_content(contents)
                    
                    generated_image = None
                    for part in response.candidates[0].content.parts:
                        if part.inline_data:
                            generated_image = Image.open(io.BytesIO(part.inline_data.data))
                            break
                    if generated_image is None: raise ValueError(f"모델이 이미지를 반환하지 않았습니다. 응답: {response.text}")

                    # 3-3. 결과물 저장 (기존 로직과 완전히 동일)
                    safe_workflow_name = "".join(c for c in self.current_workflow_name if c.isalnum() or c in (' ', '_')).rstrip().replace(' ', '_')
                    workflow_output_dir = os.path.join(self.OUTPUT_DIR, safe_workflow_name)
                    os.makedirs(workflow_output_dir, exist_ok=True)
                    
                    safe_filename = "".join(c for c in node_name if c.isalnum() or c in (' ', '_')).rstrip().replace(' ', '_')
                    if not safe_filename: safe_filename = f"node_{i + 1}"
                    
                    if iterations > 1:
                        output_filename = f"{safe_filename}_batch{batch_index + 1}.png"
                    else:
                        output_filename = f"{safe_filename}.png"
                        
                    final_path = os.path.join(workflow_output_dir, output_filename)
                    generated_image.save(final_path)

                    # 3-4. 결과물을 다음 노드와 GUI를 위해 기록
                    self.node_outputs[node_name] = generated_image
                    
                    # GUI 업데이트: 큐를 통해 이미지 표시 요청
                    self.ui_queue.put(("display_image", (generated_image, node)))

            # 4. 모든 작업 완료 메시지
            final_status = f"파이프라인 실행 완료! 총 {len(self.pipeline_nodes) * iterations}개의 이미지가 저장되었습니다."
            final_info = "파이프라인 실행이 완료되었습니다!\n각 노드의 결과가 개별 파일로 저장되었습니다."
            self.ui_queue.put(("update_status", final_status))
            self.ui_queue.put(("show_info", final_info))

        except Exception as e:
            # 오류 발생 시 GUI 업데이트
            error_status = f"오류 발생: {e}"
            error_message = f"파이프라인 실행 중 오류가 발생했습니다:\n{e}"
            self.ui_queue.put(("update_status", error_status))
            self.ui_queue.put(("show_error", error_message))
        
        finally:
            # 작업이 성공하든 실패하든, 마지막에 버튼을 다시 활성화해야 합니다.
            # 이 작업은 메인 스레드에서 직접 처리해야 하므로, 간단한 트릭을 사용합니다.
            self.root.after(0, lambda: self.execute_btn.config(state="normal", text="전체 파이프라인 실행"))

    def execute_single_node(self, target_node):
        """지정된 단일 노드만 독립적으로 실행합니다."""
        if not all([self.base_image_path, self.system_prompt_data, self.api_key]):
            messagebox.showwarning("준비 부족", "개별 노드를 실행하려면 최소한 전역 기본 이미지, 시스템 프롬프트, API키가 필요합니다.")
            return

        try:
            node_name = target_node["name_entry"].get().strip()
            if not node_name:
                messagebox.showwarning("이름 필요", "실행할 노드의 이름이 비어있습니다.")
                return

            self.update_status(f"개별 노드 '{node_name}' 실행 준비...")

            # 1. 입력 이미지 결정 (캐시된 결과물 사용)
            parent_selection = target_node["parent_var"].get()
            input_image = None
            
            # 'node_outputs' 캐시가 비어있다면, 전역 이미지를 채워준다.
            if not self.node_outputs:
                self.node_outputs["전역 기본 이미지"] = Image.open(self.base_image_path)

            if parent_selection == "이전 노드":
                # 현재 노드의 인덱스를 찾아 이전 노드의 이름을 알아낸다.
                try:
                    current_index = self.pipeline_nodes.index(target_node)
                    if current_index == 0:
                        input_image = self.node_outputs["전역 기본 이미지"]
                    else:
                        previous_node_name = self.pipeline_nodes[current_index - 1]["name_entry"].get().strip()
                        if not previous_node_name: raise KeyError
                        input_image = self.node_outputs[previous_node_name]
                except (ValueError, KeyError):
                    messagebox.showerror("오류", f"이전 노드의 결과물을 찾을 수 없습니다. 먼저 전체 파이프라인이나 이전 노드를 실행해주세요.")
                    return
            else:
                if parent_selection not in self.node_outputs:
                    messagebox.showerror("오류", f"입력으로 지정된 '{parent_selection}'의 결과물을 찾을 수 없습니다. 먼저 전체 파이프라인이나 해당 노드를 실행해주세요.")
                    return
                input_image = self.node_outputs[parent_selection]

            # 2. API 호출 (execute_pipeline과 로직 공유)
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel('gemini-2.5-flash-image-preview')
            system_prompt = self.system_prompt_data.get("prompt", "")
            
            aux_prompt = target_node["prompt_entry"].get()
            instructional_prefix = "You are an image generation pipeline..." # (이하 프롬프트 구성 동일)
            full_prompt = f"{instructional_prefix}\n\n## System Prompt:\n{system_prompt}\n\n## User Instruction for this step:\n{aux_prompt}"
            
            contents = [full_prompt, input_image]
            if target_node["node_image_path"]:
                contents.append(Image.open(target_node["node_image_path"]))
            
            self.update_status(f"개별 노드 '{node_name}' 실행 중...")
            response = model.generate_content(contents)
            
            generated_image = None
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    generated_image = Image.open(io.BytesIO(part.inline_data.data))
                    break
            if generated_image is None: raise ValueError("모델이 이미지를 반환하지 않았습니다.")

            # 3. 결과 저장 및 캐시 업데이트
            safe_workflow_name = "".join(c for c in self.current_workflow_name if c.isalnum() or c in (' ', '_')).rstrip().replace(' ', '_')
            workflow_output_dir = os.path.join(self.OUTPUT_DIR, safe_workflow_name)
            os.makedirs(workflow_output_dir, exist_ok=True)
            safe_filename = "".join(c for c in node_name if c.isalnum() or c in (' ', '_')).rstrip().replace(' ', '_')
            output_filename = f"{safe_filename}_single.png" # 단일 실행임을 표시
            final_path = os.path.join(workflow_output_dir, output_filename)
            generated_image.save(final_path)

            self.node_outputs[node_name] = generated_image
            self.display_image(generated_image, target_node["result_image_label"])
            self.update_status(f"개별 노드 '{node_name}' 실행 완료! '{final_path}'에 저장됨.")

        except Exception as e:
            self.update_status(f"오류 발생: {e}")
            messagebox.showerror("오류", f"개별 노드 실행 중 오류가 발생했습니다:\n{e}")
    

if __name__ == "__main__":
    root = tk.Tk()
    app = ImagePipelineApp(root)
    root.mainloop()