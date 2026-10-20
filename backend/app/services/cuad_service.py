import os
import torch
from transformers import AutoModelForQuestionAnswering, AutoTokenizer

class CUADService:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CUADService, cls).__new__(cls)
            cls._instance.model = None
            cls._instance.tokenizer = None
            cls._instance.device = "cpu"
            cls._instance._initialized = False
        return cls._instance

    def _initialize(self):
        if self._initialized:
            return
        self._initialized = True
        # Resolve the path to the CUAD model
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        local_model_path = os.path.join(base_dir, "../cuad/train_models/cuad-roberta-base/")
        local_model_path = os.path.abspath(local_model_path)
        
        # Check if local model exists, otherwise fallback to Hugging Face Hub
        if os.path.exists(local_model_path) and os.listdir(local_model_path):
            model_id_or_path = local_model_path
            print(f"Loading local CUAD RoBERTa model from {model_id_or_path}...")
        else:
            model_id_or_path = "Rakib/roberta-base-on-cuad"
            print(f"Loading CUAD model '{model_id_or_path}' from Hugging Face Hub...")
            
        # Determine the best device
        if torch.cuda.is_available():
            device = "cuda"
        elif torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
            
        self.device = device
        print(f"Loading CUAD RoBERTa model from {model_id_or_path} on {device}...")
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_id_or_path)
            self.model = AutoModelForQuestionAnswering.from_pretrained(model_id_or_path)
            self.model.to(device)
            self.model.eval()
            print("CUAD model and tokenizer loaded successfully.")
        except Exception as e:
            print(f"Failed to load CUAD model: {e}")
            self.model = None
            self.tokenizer = None

    def extract_answer(self, question: str, context: str):
        """
        Extracts the answer from the context given a question.
        Returns a dict with 'score', 'start', 'end', 'answer' if successful, else None.
        """
        if not self._initialized:
            self._initialize()
        if not self.model or not self.tokenizer:
            return None
            
        try:
            inputs = self.tokenizer(
                question,
                context,
                return_tensors="pt",
                max_length=512,
                truncation="only_second"
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = self.model(**inputs)

            start_logits = outputs.start_logits[0]
            end_logits = outputs.end_logits[0]

            s_idx = torch.argmax(start_logits).item()
            e_idx = torch.argmax(end_logits).item()

            if s_idx == 0 or e_idx == 0 or e_idx < s_idx:
                return {"score": 0.0, "start": 0, "end": 0, "answer": ""}

            s_prob = torch.softmax(start_logits, dim=-1)[s_idx].item()
            e_prob = torch.softmax(end_logits, dim=-1)[e_idx].item()
            score = float(s_prob * e_prob)

            answer_ids = inputs["input_ids"][0][s_idx : e_idx + 1]
            answer = self.tokenizer.decode(answer_ids, skip_special_tokens=True).strip()

            return {
                "score": score,
                "start": s_idx,
                "end": e_idx,
                "answer": answer
            }
        except Exception as e:
            print(f"Error during extraction: {e}")
            return None

cuad_service = CUADService()
