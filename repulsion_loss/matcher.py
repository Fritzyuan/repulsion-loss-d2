import torch

from detectron2.modeling.matcher import Matcher


class Top2Matcher(Matcher):

    def __init__(self, thresholds, labels, allow_low_quality_matches=False):
        super().__init__(thresholds, labels, allow_low_quality_matches)

    def __call__(self, match_quality_matrix):
        """
        Args:
            match_quality_matrix (Tensor[float]): an MxN tensor, containing the
                pairwise quality between M ground-truth elements and N predicted
                elements. All elements must be >= 0 (due to the us of `torch.nonzero`
                for selecting indices in :meth:`set_low_quality_matches_`).

        Returns:
            matches (Tensor[int64]): a vector of length N, where matches[i] is a matched
                ground-truth index in [0, M); attraction targets
            match_labels (Tensor[int8]): a vector of length N, where match_labels[i] indicates
                whether a prediction is a true or false positive or ignored. 
                (Label set = self.labels; usually = { -1, 0, 1 })
            repel_matches (Tensor[int64]): a vector of length N, where repel_matches[i] is a matched
                ground-truth index in [0, M) for repulsion; i.e. for each proposal, the ground truth 
                box with the highest IOU which is not its designated target.
                repel_matches[i] should be ignored if matches[i] is not a foreground label, or if
                num ground truths < 2.
        """
        assert match_quality_matrix.dim() == 2

        if match_quality_matrix.numel() == 0:
            default_matches = match_quality_matrix.new_full(
                (match_quality_matrix.size(1),), 0, dtype=torch.int64
            )
            repel_default_matches = match_quality_matrix.new_full(
                (match_quality_matrix.size(1),), 0, dtype=torch.int64
            )
            # When no gt boxes exist, we define IOU = 0 and therefore set labels
            # to `self.labels[0]`, which usually defaults to background class 0
            # To choose to ignore instead, can make labels=[-1,0,-1,1] + set appropriate thresholds
            default_match_labels = match_quality_matrix.new_full(
                (match_quality_matrix.size(1),), self.labels[0], dtype=torch.int8
            )
            return default_matches, default_match_labels, repel_default_matches

        assert torch.all(match_quality_matrix >= 0)

        # match_quality_matrix is M (gt) x N (predicted)
        # Max over gt elements (dim 0) to find best gt candidate for each prediction
        if (match_quality_matrix.size(0) > 1):
            # for repulsion loss, we look for 2nd place match as repulsion target
            topk_vals, topk_matches = match_quality_matrix.topk(k=2, dim=0)
            matched_vals, matches = topk_vals[0], topk_matches[0]
            repel_vals, repel_matches = topk_vals[1], topk_matches[1]
        else:
            # if there is only 1 ground truth box, just compute matches and 
            # return a default for repel_matches
            matched_vals, matches = match_quality_matrix.max(dim=0)
            repel_matches = match_quality_matrix.new_full(
                (match_quality_matrix.size(1),), 0, dtype=torch.int64
            )

        match_labels = matches.new_full(matches.size(), 1, dtype=torch.int8)

        for (l, low, high) in zip(self.labels, self.thresholds[:-1], self.thresholds[1:]):
            low_high = (matched_vals >= low) & (matched_vals < high)
            match_labels[low_high] = l
        
        if self.allow_low_quality_matches:
            self.set_low_quality_matches_(match_labels, match_quality_matrix)

        return matches, match_labels, repel_matches