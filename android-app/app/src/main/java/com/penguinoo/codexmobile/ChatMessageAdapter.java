package com.penguinoo.codexmobile;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.widget.Toast;
import android.view.LayoutInflater;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import com.penguinoo.codexmobile.databinding.ItemMessageAssistantBinding;
import com.penguinoo.codexmobile.databinding.ItemMessageUserBinding;

import java.text.DateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;

public final class ChatMessageAdapter extends RecyclerView.Adapter<RecyclerView.ViewHolder> {
    private static final int VIEW_TYPE_USER = 1;
    private static final int VIEW_TYPE_ASSISTANT = 2;

    private final List<ChatMessage> items = new ArrayList<>();
    private final DateFormat dateFormat = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT);

    public void submitList(List<ChatMessage> messages) {
        items.clear();
        items.addAll(messages);
        notifyDataSetChanged();
    }

    @Override
    public int getItemViewType(int position) {
        return items.get(position).isUser() ? VIEW_TYPE_USER : VIEW_TYPE_ASSISTANT;
    }

    @NonNull
    @Override
    public RecyclerView.ViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        LayoutInflater inflater = LayoutInflater.from(parent.getContext());
        if (viewType == VIEW_TYPE_USER) {
            return new UserMessageViewHolder(ItemMessageUserBinding.inflate(inflater, parent, false));
        }
        return new AssistantMessageViewHolder(ItemMessageAssistantBinding.inflate(inflater, parent, false));
    }

    @Override
    public void onBindViewHolder(@NonNull RecyclerView.ViewHolder holder, int position) {
        ChatMessage message = items.get(position);
        if (holder instanceof UserMessageViewHolder) {
            ((UserMessageViewHolder) holder).bind(message);
        } else if (holder instanceof AssistantMessageViewHolder) {
            ((AssistantMessageViewHolder) holder).bind(message);
        }
    }

    @Override
    public int getItemCount() {
        return items.size();
    }

    private String formatTime(long timestamp) {
        if (timestamp <= 0L) {
            return "";
        }
        return dateFormat.format(new Date(timestamp * 1000L));
    }

    final class UserMessageViewHolder extends RecyclerView.ViewHolder {
        private final ItemMessageUserBinding binding;

        UserMessageViewHolder(ItemMessageUserBinding binding) {
            super(binding.getRoot());
            this.binding = binding;
        }

        void bind(ChatMessage message) {
            binding.messageText.setText(message.text);
            binding.timeText.setText(message.isEphemeral
                    ? binding.getRoot().getContext().getString(R.string.label_sending)
                    : formatTime(message.timestamp));
            binding.getRoot().setOnLongClickListener(view -> {
                copyMessageText(message.text);
                return true;
            });
        }

        private void copyMessageText(String text) {
            Context context = binding.getRoot().getContext();
            ClipboardManager clipboardManager = (ClipboardManager) context.getSystemService(Context.CLIPBOARD_SERVICE);
            if (clipboardManager == null) {
                return;
            }
            clipboardManager.setPrimaryClip(ClipData.newPlainText("Codex chat", text));
            Toast.makeText(context, R.string.banner_message_copied, Toast.LENGTH_SHORT).show();
        }
    }

    final class AssistantMessageViewHolder extends RecyclerView.ViewHolder {
        private final ItemMessageAssistantBinding binding;

        AssistantMessageViewHolder(ItemMessageAssistantBinding binding) {
            super(binding.getRoot());
            this.binding = binding;
        }

        void bind(ChatMessage message) {
            binding.messageText.setText(message.text);
            binding.timeText.setText(message.isEphemeral
                    ? binding.getRoot().getContext().getString(R.string.label_codex_replying)
                    : formatTime(message.timestamp));
            binding.getRoot().setOnLongClickListener(view -> {
                copyMessageText(message.text);
                return true;
            });
        }

        private void copyMessageText(String text) {
            Context context = binding.getRoot().getContext();
            ClipboardManager clipboardManager = (ClipboardManager) context.getSystemService(Context.CLIPBOARD_SERVICE);
            if (clipboardManager == null) {
                return;
            }
            clipboardManager.setPrimaryClip(ClipData.newPlainText("Codex chat", text));
            Toast.makeText(context, R.string.banner_message_copied, Toast.LENGTH_SHORT).show();
        }
    }
}
