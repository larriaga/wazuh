/*
 * Queue (abstract data type)
 * Copyright (C) 2017 Wazuh Inc.
 * October 2, 2017
 *
 * This program is a free software; you can redistribute it
 * and/or modify it under the terms of the GNU General Public
 * License (version 2) as published by the FSF - Free Software
 * Foundation.
 */

#include <shared.h>

w_queue_t * queue_init(size_t size) {
    w_queue_t * queue;
    os_calloc(1, sizeof(w_queue_t), queue);
    os_malloc(size * sizeof(void *), queue->data);
    queue->size = size;
    pthread_mutex_init(&queue->mutex, NULL);
    pthread_cond_init(&queue->available, NULL);
    return queue;
}

void queue_free(w_queue_t * queue) {
    if (queue) {
        free(queue->data);
        pthread_mutex_destroy(&queue->mutex);
        pthread_cond_destroy(&queue->available);
        free(queue);
    }
}

int queue_full(const w_queue_t * queue) {
    return (queue->begin + 1) % queue->size == queue->end;
}

int queue_empty(const w_queue_t * queue) {
    return queue->begin == queue->end;
}

int queue_push(w_queue_t * queue, void * data) {
    if (queue_full(queue)) {
        return -1;
    } else {
        queue->data[queue->begin] = data;
        queue->begin = (queue->begin + 1) % queue->size;
        return 0;
    }
}

int queue_push_ex(w_queue_t * queue, void * data) {
    int result;

    w_mutex_lock(&queue->mutex);

    if (result = queue_push(queue, data), result == 0) {
        w_cond_signal(&queue->available);
    }

    w_mutex_unlock(&queue->mutex);
    return result;
}

void * queue_pop(w_queue_t * queue) {
    void * data;

    if (queue_empty(queue)) {
        return NULL;
    } else {
        data = queue->data[queue->end];
        queue->data[queue->begin] = data;
        queue->end = (queue->end + 1) % queue->size;
        return data;
    }
}

void * queue_pop_ex(w_queue_t * queue) {
    void * data;

    w_mutex_lock(&queue->mutex);

    while (data = queue_pop(queue), !data) {
        w_cond_wait(&queue->available, &queue->mutex);
    }

    w_mutex_unlock(&queue->mutex);
    return data;
}
