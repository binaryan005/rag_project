
import os
import re

import torch
from transformers import AutoTokenizer, AutoModelForQuestionAnswering


class CUADService:
    _instance = None

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

        # Resolve the path to the CUAD model
        base_dir = os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.abspath(__file__)
                )
            )
        )

        local_model_path = os.path.abspath(
            os.path.join(
                base_dir,
                "../cuad/train_models/cuad-roberta-base/"
            )
        )

        # Load local model if available, otherwise use Hugging Face Hub
        if (
            os.path.exists(local_model_path)
            and os.listdir(local_model_path)
        ):
            model_id_or_path = local_model_path

            print(
                f"Loading local CUAD RoBERTa model from "
                f"{model_id_or_path}..."
            )

        else:
            model_id_or_path = "Rakib/roberta-base-on-cuad"

            print(
                f"Loading CUAD model '{model_id_or_path}' "
                "from Hugging Face Hub..."
            )

        # Determine the best available device
        if torch.cuda.is_available():
            self.device = "cuda"

        elif (
            hasattr(torch.backends, "mps")
            and torch.backends.mps.is_available()
        ):
            self.device = "mps"

        else:
            self.device = "cpu"

        print(
            f"Loading CUAD RoBERTa model from "
            f"{model_id_or_path} on {self.device}..."
        )

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                model_id_or_path
            )

            self.model = AutoModelForQuestionAnswering.from_pretrained(
                model_id_or_path
            )

            self.model.to(self.device)
            self.model.eval()

            self._initialized = True

            print("CUAD model and tokenizer loaded successfully.")

        except Exception as e:
            print(f"Failed to load CUAD model: {e}")

            self.model = None
            self.tokenizer = None
            self._initialized = False

    def extract_answer(
        self,
        question: str,
        context: str,
        max_length: int = 512
    ):
        """
        Extracts an answer from the supplied context using CUAD RoBERTa.

        Returns:
            {
                "score": float,
                "diff": float,
                "start": int,
                "end": int,
                "answer": str
            }

        Returns None if extraction fails.
        """

        if not context or not context.strip():
            return None

        # Lazy initialization
        if not self._initialized:
            self._initialize()

        if self.model is None or self.tokenizer is None:
            return None

        try:
            inputs = self.tokenizer(
                question,
                context,
                return_tensors="pt",
                truncation="only_second",
                max_length=max_length
            )

            input_ids = inputs["input_ids"][0]

            # RoBERTa pair format:
            # <s> question </s></s> context </s>

            sep_indices = (
                input_ids == self.tokenizer.sep_token_id
            ).nonzero(as_tuple=True)[0]

            if len(sep_indices) < 2:
                return None

            # Identify the context token boundaries
            context_start = sep_indices[1].item() + 1
            context_end = sep_indices[-1].item() - 1

            if context_end < context_start:
                return None

            # Move tensors to the selected device
            inputs_device = {
                key: value.to(self.device)
                for key, value in inputs.items()
            }

            # Model inference
            with torch.no_grad():
                outputs = self.model(**inputs_device)

            start_logits = outputs.start_logits[0].cpu()
            end_logits = outputs.end_logits[0].cpu()

            # Null-answer score
            null_score = (
                start_logits[0] + end_logits[0]
            ).item()

            # Restrict extraction to context tokens
            s_logits = start_logits[
                context_start:context_end + 1
            ]

            e_logits = end_logits[
                context_start:context_end + 1
            ]

            n = s_logits.size(0)

            if n == 0:
                return None

            # Calculate all possible start/end span scores
            span_matrix = (
                s_logits.unsqueeze(1)
                + e_logits.unsqueeze(0)
            )

            i_indices = (
                torch.arange(n)
                .unsqueeze(1)
                .expand(n, n)
            )

            j_indices = (
                torch.arange(n)
                .unsqueeze(0)
                .expand(n, n)
            )

            # Valid spans:
            # End must follow start.
            # Maximum answer length is 150 tokens.
            mask = (
                (j_indices >= i_indices)
                & ((j_indices - i_indices) <= 150)
            )

            span_matrix[~mask] = float("-inf")

            max_val = span_matrix.max()

            if max_val.item() == float("-inf"):
                return None

            # Find the best valid answer span
            best_idx = (
                span_matrix == max_val
            ).nonzero()[0]

            s_idx = (
                best_idx[0].item() + context_start
            )

            e_idx = (
                best_idx[1].item() + context_start
            )

            span_score = max_val.item()

            # Compare answer score against null score
            diff = span_score - null_score

            confidence = torch.sigmoid(
                torch.tensor(diff)
            ).item()

            # Decode the extracted answer
            ans_text = self.tokenizer.decode(
                input_ids[s_idx:e_idx + 1],
                skip_special_tokens=True
            ).strip()

            # Remove leading punctuation
            ans_text = re.sub(
                r"^[,\.\s;:]+",
                "",
                ans_text
            ).strip()

            # Reject empty or invalid answers
            if (
                len(ans_text) < 3
                or re.match(r"^[^\w]+$", ans_text)
            ):
                return None

            return {
                "score": float(confidence),
                "diff": float(diff),
                "start": int(s_idx),
                "end": int(e_idx),
                "answer": ans_text
            }

        except Exception as e:
            print(f"Error during extraction: {e}")
            return None


cuad_service = CUADService()
